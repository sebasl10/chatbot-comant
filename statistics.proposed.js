/**
 * Version générique de statistics.js : N colonnes, N séries.
 *
 * Contrat attendu depuis /statistics/select :
 * {
 *   isSaved: bool,
 *   description: "...",
 *   date: "...",
 *   graphType: "pie" | "bar" | "line" | "table",
 *   columns: [ { key, label, role: "label"|"value", format: "text"|"date"|"number"|"hours"|"seconds"|"percent" } ],
 *   results: [ { <key>: <valeur>, ... }, ... ]
 * }
 *
 * `columns` = colonne `labels` (JSON) de la table `statistics`, à parser côté serveur.
 * `graphType` = colonne `graph_type`.
 */
import Chart from 'chart.js/auto';

const CHART_COLORS = [
    '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
    '#FF9F40', '#C9CBCF', '#66FF66', '#66CCFF', '#FFCC99',
    '#FF33AA', '#33FF99', '#FF66CC', '#66FFFF', '#FF9966'
];

/**
 * Un camembert peut avoir beaucoup de parts (un par salarié, par projet...).
 * Au-delà de la palette fixe, on génère des teintes distinctes par angle d'or
 * plutôt que de recycler les mêmes 15 couleurs (deux parts identiques seraient
 * indiscernables dans la légende).
 */
function buildColors(count) {
    if (count <= CHART_COLORS.length) {
        return CHART_COLORS.slice(0, count);
    }
    return Array.from({ length: count }, (_, i) => {
        if (i < CHART_COLORS.length) return CHART_COLORS[i];
        const hue = Math.round((i * 137.508) % 360);
        const lightness = i % 2 === 0 ? 65 : 50;
        return `hsl(${hue}, 70%, ${lightness}%)`;
    });
}

let currentStatisticData = {
    name: '',
    description: '',
    date: '',
    columns: [],
    rows: [],
    graphType: 'table'
};
let windowStatisticsChart = null;

// Tri : { index: <index de colonne>, state: 'default' | 'ascending' | 'descending' }
let sortState = { index: 0, state: 'default' };

/* ------------------------------------------------------------------ */
/* Métadonnées de colonnes                                             */
/* ------------------------------------------------------------------ */

/**
 * Renvoie les descripteurs de colonnes. Si le back n'en fournit pas (anciennes
 * statistiques enregistrées avant la migration), on retombe sur l'ancien
 * comportement : 1ʳᵉ colonne = label, les suivantes = valeurs.
 */
function resolveColumns(data) {
    if (Array.isArray(data.columns) && data.columns.length > 0) {
        return data.columns;
    }
    if (!data.results || data.results.length === 0) {
        return [];
    }
    return Object.keys(data.results[0]).map((key, index) => ({
        key: key,
        label: key,
        role: index === 0 ? 'label' : 'value',
        format: index === 0 ? 'text' : 'number'
    }));
}

const labelColumns = (columns) => columns.filter(c => c.role === 'label');
const valueColumns = (columns) => columns.filter(c => c.role === 'value');

/** Un graphe n'est possible que s'il y a exactement 1 colonne de catégorie et ≥ 1 série. */
function canRenderChart(graphType, columns, rows) {
    if (!graphType || graphType === 'table') return false;
    if (!rows || rows.length === 0) return false;
    if (labelColumns(columns).length !== 1) return false;

    const values = valueColumns(columns);
    if (values.length === 0) return false;
    if (graphType === 'pie' && values.length !== 1) return false;

    return true;
}

/* ------------------------------------------------------------------ */
/* Formatage des valeurs                                               */
/* ------------------------------------------------------------------ */

function formatValue(value, format) {
    if (value === null || value === undefined || value === '') return '';

    switch (format) {
        case 'seconds':
            return window.durationConverter(Number(value), 'h min s');
        case 'hours':
            // Le SQL renvoie des heures décimales, durationConverter attend des secondes.
            return window.durationConverter(Number(value) * 3600, 'h min s');
        case 'percent':
            return `${Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} %`;
        case 'number':
            return Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 2 });
        case 'date':
        case 'text':
        default:
            return String(value);
    }
}

/**
 * Formatage des graduations de l'axe Y : une durée y est écrite de façon compacte
 * ("194 h"), le `h min s` complet restant réservé à la table et aux tooltips.
 */
function formatAxisValue(value, format) {
    if (format !== 'seconds') return formatValue(value, format);

    const seconds = Number(value);
    if (seconds === 0) return '0';
    if (Math.abs(seconds) < 3600) return `${Math.round(seconds / 60)} min`;
    return `${Number((seconds / 3600).toFixed(1)).toLocaleString('fr-FR')} h`;
}

/* ------------------------------------------------------------------ */
/* Chargement                                                          */
/* ------------------------------------------------------------------ */

$(function () {
    $('#statistics-select').trigger('change');

    $('#statistics-select').on('change', function () {
        const selectedVal = $(this).val();
        if (!selectedVal) {
            resetStatisticsView();
            return;
        }

        $.ajax({
            url: '/statistics/select',
            method: 'GET',
            data: { id: selectedVal }
        }).done(function (data) {
            if (data.isSaved !== true) {
                $('#statistics-save').show();
            } else {
                $('#statistics-save').hide();
            }
            $('#statistics-delete').show();
            $('#statistics-information').show();

            $('#statistics-description').html('<strong>Description:</strong> ' + (data.description || ''));
            $('#statistics-date').html('<strong>Date de recherche:</strong> ' + (data.date || ''));

            const rows = data.results || [];
            if (rows.length === 0) {
                clearStatisticsData();
                return;
            }

            const columns = resolveColumns(data);
            // Si le type demandé n'est pas représentable, on retombe sur la table.
            const graphType = canRenderChart(data.graphType, columns, rows) ? data.graphType : 'table';

            currentStatisticData = {
                name: $('#statistics-select option:selected').text(),
                description: data.description || '',
                date: data.date || '',
                columns: columns,
                rows: rows,
                graphType: graphType
            };

            sortState = { index: 0, state: 'default' };
            renderStatisticsTable(rows, columns);

            if (graphType === 'table') {
                destroyChart();
                $('#statistics-graph-container').removeClass('visible');
            } else {
                initStatisticsChart(rows, columns, graphType);
                $('#statistics-graph-container').addClass('visible');
            }

            $('#statistics-download-pdf').show();
        });
    });

    $('#statistics-download-pdf').on('click', function () {
        downloadStatisticsPDF();
    });

    $(document).on('click', '#statistics-delete', function () {
        const selectedVal = $('#statistics-select').val();
        $.ajax({
            url: '/statistics/delete',
            method: 'POST',
            data: { id: selectedVal }
        }).done(function () {
            $('#statistics-select option[value="' + selectedVal + '"]').remove();
            $('#statistics-select').val('');
            $('#statistics-select').selectpicker('refresh');
            $('#statistics-select').trigger('change');
        });
    });
});

function destroyChart() {
    if (windowStatisticsChart) {
        windowStatisticsChart.destroy();
        windowStatisticsChart = null;
    }
}

function clearStatisticsData() {
    currentStatisticData = { name: '', description: '', date: '', columns: [], rows: [], graphType: 'table' };
    $('#statistics-graph-container').removeClass('visible');
    $('#statistics-table-header').html('');
    $('#statistics-table-body').html('');
    $('#statistics-download-pdf').hide();
    destroyChart();
}

function resetStatisticsView() {
    $('#statistics-save').hide();
    $('#statistics-delete').hide();
    $('#statistics-information').hide();
    $('#statistics-description').html('');
    $('#statistics-date').html('');
    clearStatisticsData();
}

/* ------------------------------------------------------------------ */
/* Table (N colonnes, tri sur n'importe quelle colonne)                */
/* ------------------------------------------------------------------ */

function renderStatisticsTable(rows, columns) {
    const $tableHeader = $('#statistics-table-header');
    const $tableBody = $('#statistics-table-body');

    const displayRows = sortRows(rows, columns);

    const headerCells = columns.map((col, index) => {
        const indicator = index === sortState.index ? sortIndicator(sortState.state) : '↻';
        return `<th class="sortable-header" data-column-index="${index}">
                    ${escapeHtml(col.label)} <span class="sort-indicator">${indicator}</span>
                </th>`;
    }).join('');

    $tableHeader.html(`<tr>${headerCells}</tr>`);

    const body = displayRows.map(row => {
        const cells = columns.map(col => `<td>${escapeHtml(formatValue(row[col.key], col.format))}</td>`).join('');
        return `<tr>${cells}</tr>`;
    }).join('');

    $tableBody.html(body);

    $('.sortable-header').off('click').on('click', function () {
        const index = Number($(this).data('column-index'));
        if (index !== sortState.index) {
            sortState = { index: index, state: 'ascending' };
        } else {
            switch (sortState.state) {
                case 'default': sortState.state = 'ascending'; break;
                case 'ascending': sortState.state = 'descending'; break;
                default: sortState = { index: 0, state: 'default' };
            }
        }
        renderStatisticsTable(rows, columns);
    });
}

function sortIndicator(state) {
    if (state === 'ascending') return '↑';
    if (state === 'descending') return '↓';
    return '↻';
}

function sortRows(rows, columns) {
    if (sortState.state === 'default') return rows;

    const col = columns[sortState.index];
    if (!col) return rows;

    const direction = sortState.state === 'ascending' ? 1 : -1;
    const numeric = col.role === 'value' || ['number', 'hours', 'seconds', 'percent'].includes(col.format);

    // copie : on ne réordonne jamais les données d'origine (le graphe garde son ordre SQL)
    return rows.slice().sort((a, b) => {
        const va = a[col.key];
        const vb = b[col.key];
        if (numeric) {
            return ((parseFloat(va) || 0) - (parseFloat(vb) || 0)) * direction;
        }
        return String(va ?? '').localeCompare(String(vb ?? ''), 'fr') * direction;
    });
}

function escapeHtml(value) {
    return $('<div>').text(value == null ? '' : value).html();
}

/* ------------------------------------------------------------------ */
/* Graphe (1 dataset par colonne `value`)                              */
/* ------------------------------------------------------------------ */

function initStatisticsChart(rows, columns, type = 'pie') {
    destroyChart();

    const categoryColumn = labelColumns(columns)[0];
    const series = valueColumns(columns);
    const labels = rows.map(row => formatValue(row[categoryColumn.key], categoryColumn.format));

    const datasets = series.map((col, index) => {
        // Camembert : une couleur par part. Bar/line : une couleur par série.
        const colors = type === 'pie'
            ? buildColors(rows.length)
            : buildColors(series.length)[index];

        return {
            label: col.label,
            data: rows.map(row => parseFloat(row[col.key]) || 0),
            backgroundColor: colors,
            borderColor: colors,
            borderWidth: 1,
            // mémorisé pour formater tooltips et axes selon la série
            statFormat: col.format
        };
    });

    const canvas = document.getElementById('statisticsPie');
    canvas.style.height = '350px';
    canvas.style.width = '100%';

    const config = {
        type: type,
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const format = context.dataset.statFormat;
                            const formatted = formatValue(context.raw, format);
                            // Plusieurs séries : on rappelle laquelle
                            return datasets.length > 1
                                ? `${context.dataset.label} : ${formatted}`
                                : formatted;
                        }
                    }
                }
            }
        }
    };

    if (type === 'bar' || type === 'line') {
        // Les séries d'un même graphe partagent le même format (garanti par l'agent)
        const axisFormat = series[0].format;
        config.options.scales = {
            y: {
                beginAtZero: true,
                ticks: { callback: (value) => formatAxisValue(value, axisFormat) }
            },
            x: { grid: { display: false } }
        };
    }

    windowStatisticsChart = new Chart(canvas.getContext('2d'), config);
}

/**
 * Légende HTML. Pour un camembert, chaque entrée est une PART (index de donnée) ;
 * pour bar/line avec plusieurs séries, chaque entrée est un DATASET.
 */
const htmlLegendPlugin = {
    id: 'htmlLegend',

    afterUpdate(chart) {
        const legendId = chart.canvas.dataset.legend;
        if (!legendId) return;

        const legendContainer = document.getElementById(legendId);
        if (!legendContainer) return;

        legendContainer.innerHTML = '';

        const byDataset = chart.config.type !== 'pie' && chart.config.type !== 'doughnut';
        const items = chart.options.plugins.legend.labels.generateLabels(chart);

        items.forEach(item => {
            const li = document.createElement('li');
            li.style.display = 'flex';
            li.style.alignItems = 'center';
            li.style.cursor = 'pointer';
            li.style.userSelect = 'none';

            const hidden = byDataset
                ? !chart.isDatasetVisible(item.datasetIndex)
                : chart.getDataVisibility(item.index) === false;

            li.style.textDecoration = hidden ? 'line-through' : 'none';
            li.style.opacity = hidden ? '0.5' : '1';

            li.onclick = () => {
                if (byDataset) {
                    chart.setDatasetVisibility(item.datasetIndex, !chart.isDatasetVisible(item.datasetIndex));
                } else {
                    chart.toggleDataVisibility(item.index);
                }
                chart.update();
            };

            const box = document.createElement('span');
            box.style.background = item.fillStyle;
            box.style.width = '12px';
            box.style.height = '12px';
            box.style.display = 'inline-block';
            box.style.marginRight = '6px';

            const text = document.createElement('span');
            text.innerText = item.text;

            li.appendChild(box);
            li.appendChild(text);
            legendContainer.appendChild(li);

            // Survol : uniquement pour les parts d'un camembert
            if (!byDataset) {
                li.onmouseenter = () => {
                    if (!chart.hovering) {
                        chart.hovering = true;
                        chart.setActiveElements([{ datasetIndex: 0, index: item.index }]);
                        chart.tooltip.setActiveElements([{ datasetIndex: 0, index: item.index }], { x: 0, y: 0 });
                        chart.update();
                    }
                };
                li.onmouseleave = () => {
                    chart.hovering = false;
                    chart.setActiveElements([]);
                    chart.tooltip.setActiveElements([], { x: 0, y: 0 });
                    chart.update();
                };
            }
        });
    }
};
Chart.register(htmlLegendPlugin);

/* ------------------------------------------------------------------ */
/* PDF                                                                 */
/* ------------------------------------------------------------------ */

function downloadStatisticsPDF() {
    if (!currentStatisticData.rows || currentStatisticData.rows.length === 0) {
        alert('Aucune statistique à exporter');
        return;
    }

    if (typeof html2pdf === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js';
        script.onload = generatePDF;
        script.onerror = function () {
            alert('Erreur de chargement de html2pdf. Veuillez réessayer.');
        };
        document.head.appendChild(script);
    } else {
        generatePDF();
    }

    function generatePDF() {
        const pdfContainer = document.createElement('div');
        pdfContainer.id = 'temp-pdf-container';
        pdfContainer.style.position = 'absolute';
        pdfContainer.style.left = '-10000px';
        pdfContainer.style.top = '0';
        pdfContainer.style.zIndex = '-1';

        const pdfContent = document.createElement('div');
        pdfContent.className = 'pdf-content';
        pdfContent.style.padding = '20px';
        pdfContent.style.maxWidth = '1200px';
        pdfContent.style.background = 'white';
        pdfContent.style.fontFamily = 'Arial, sans-serif';

        const title = document.createElement('h2');
        title.textContent = currentStatisticData.name;
        title.style.textAlign = 'center';
        title.style.marginBottom = '20px';
        pdfContent.appendChild(title);

        const infoDiv = document.createElement('div');
        infoDiv.style.marginBottom = '20px';
        infoDiv.innerHTML = `
            <p><strong>Description:</strong> ${escapeHtml(currentStatisticData.description)}</p>
            <p><strong>Date:</strong> ${escapeHtml(currentStatisticData.date)}</p>
        `;
        pdfContent.appendChild(infoDiv);

        const contentContainer = document.createElement('div');
        contentContainer.style.marginTop = '20px';

        const tableContainer = document.createElement('div');
        tableContainer.style.width = '100%';
        tableContainer.style.marginBottom = '20px';
        tableContainer.appendChild(document.getElementById('statistics-data-table').cloneNode(true));
        contentContainer.appendChild(tableContainer);

        const graphContainer = document.createElement('div');
        graphContainer.style.width = '100%';

        let img = null;
        if (currentStatisticData.graphType !== 'table') {
            img = document.createElement('img');
            img.src = document.getElementById('statisticsPie').toDataURL('image/png');
            img.style.width = '100%';
            img.style.maxHeight = '350px';
            graphContainer.appendChild(img);

            const legendContainer = document.createElement('div');
            legendContainer.style.display = 'flex';
            legendContainer.style.flexWrap = 'wrap';
            legendContainer.style.gap = '8px';
            legendContainer.style.justifyContent = 'center';
            legendContainer.style.marginTop = '10px';
            legendContainer.innerHTML = document.getElementById('statisticsLegend').innerHTML;
            graphContainer.appendChild(legendContainer);
        }

        contentContainer.appendChild(graphContainer);
        pdfContent.appendChild(contentContainer);
        pdfContainer.appendChild(pdfContent);
        document.body.appendChild(pdfContainer);

        if (img) {
            img.onload = generatePDFFromElement;
            if (img.complete) generatePDFFromElement();
        } else {
            generatePDFFromElement();
        }

        function generatePDFFromElement() {
            const opt = {
                margin: 15,
                filename: `Statistique_${currentStatisticData.name.replace(/[^a-z0-9]/gi, '_')}.pdf`,
                jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
                html2canvas: { scale: 2, useCORS: true, allowTaint: true, backgroundColor: '#FFFFFF' }
            };

            html2pdf().from(pdfContent).set(opt).save().then(() => {
                document.body.removeChild(pdfContainer);
            }).catch(err => {
                document.body.removeChild(pdfContainer);
                console.error('Erreur PDF:', err);
                alert('Erreur lors de la génération du PDF');
            });
        }
    }
}
