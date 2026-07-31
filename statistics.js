import Chart from 'chart.js/auto';

let currentStatisticData = {
    name: '',
    description: '',
    date: '',
    labels: [],
    values: [],
    graphType: 'pie'
};
let windowStatisticsChart = null;

$(function () {
    $('#statistics-select').trigger('change');

    $('#statistics-select').on('change', function(){
        let selectedVal = $(this).val();
        if (selectedVal){
            $.ajax({
                url: '/statistics/select',
                method: 'GET',
                data: { id: selectedVal }
            }).done(function (data) {
                if (data.isSaved !== true){
                    $('#statistics-save').show();
                } else{
                    $('#statistics-save').hide();
                }
                $('#statistics-delete').show();
                $('#statistics-information').show();

                $('#statistics-description').html('<strong>Description:</strong> ' + (data.description || ''));
                $('#statistics-date').html('<strong>Date de recherche:</strong> ' + (data.date || ''));

                if (data.results && data.results.length > 0) {
                    // Extraire les labels et données depuis les résultats => La première colonne est le label et la deuxième la valeur
                    const results = data.results;
                    const firstKey = Object.keys(results[0])[0];  
                    const secondKey = Object.keys(results[0])[1];

                    const labels = results.map(r => r[firstKey]);
                    const values = results.map(r => parseFloat(r[secondKey]) || 0);
                    const graphType = data.graphType || 'pie';

                    currentStatisticData = {
                        name: $('#statistics-select option:selected').text(),
                        description: data.description || '',
                        date: data.date || '',
                        labels: labels,
                        values: values,
                        graphType: graphType
                    };

                    renderStatisticsTable(labels, values);

                    if (graphType === 'table') {
                        if (windowStatisticsChart) {
                            windowStatisticsChart.destroy();
                            windowStatisticsChart = null;
                        }
                        $('#statistics-graph-container').removeClass('visible');
                    } else {
                        initStatisticsChart(labels, values, graphType);
                        $('#statistics-graph-container').addClass('visible');
                    }

                    $('#statistics-download-pdf').show();
                } else {
                    $('#statistics-graph-container').removeClass('visible');
                    $('#statistics-table-header').html('');
                    $('#statistics-table-body').html('');
                    $('#statistics-download-pdf').hide();
                    
                    
                    if (windowStatisticsChart) {
                        windowStatisticsChart.destroy();
                        windowStatisticsChart = null;
                    }
                }
            });
        } else {
            $('#statistics-save').hide();
            $('#statistics-delete').hide();
            $('#statistics-information').hide();
            $('#statistics-description').html('');
            $('#statistics-date').html('');
            $('#statistics-graph-container').removeClass('visible');
            $('#statistics-table-header').html('');
            $('#statistics-table-body').html('');
            $('#statistics-download-pdf').hide();
            
            
            if (windowStatisticsChart) {
                windowStatisticsChart.destroy();
                windowStatisticsChart = null;
            }
        }
    });

    $('#statistics-download-pdf').on('click', function() {
        downloadStatisticsPDF();
    });

    $(document).on('click', '#statistics-delete', function (e) {
        let selectedVal = $('#statistics-select').val();
        $.ajax({
            url: '/statistics/delete',
            method: 'POST',
            data: { id: selectedVal }
        }).done(function (data) {
            $('#statistics-select option[value="' + selectedVal + '"]').remove();
            $('#statistics-select').val('');
            $('#statistics-select').selectpicker('refresh');
            $('#statistics-select').trigger('change');
        });
    })
});

const htmlLegendPlugin = {
    id: 'htmlLegend',

    afterUpdate(chart) {
        const legendId = chart.canvas.dataset.legend;
        if (!legendId) return;

        const legendContainer = document.getElementById(legendId);
        if (!legendContainer) return;

        // Vider l’ancienne légende
        legendContainer.innerHTML = '';

        const items = chart.options.plugins.legend.labels.generateLabels(chart);

        items.forEach(item => {
            const li = document.createElement('li');
            li.style.display = 'flex';
            li.style.alignItems = 'center';
            li.style.cursor = 'pointer';
            li.style.userSelect = 'none';

            // Vérifie si le secteur est visible
            const hidden = chart.getDataVisibility(item.index) === false;
            li.style.textDecoration = hidden ? 'line-through' : 'none';
            li.style.opacity = hidden ? '0.5' : '1';

            li.onclick = () => {
                chart.toggleDataVisibility(item.index);
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

            // --- Hover sur la légende ---
            li.onmouseenter = () => {
                if (!chart.hovering) {
                    chart.hovering = true; // 🔥 flag custom
                    chart.setActiveElements([{ datasetIndex: 0, index: item.index }]);
                    chart.tooltip.setActiveElements(
                        [{ datasetIndex: 0, index: item.index }],
                        { x: 0, y: 0 }
                    );

                    chart.update();
                }
            };

            li.onmouseleave = () => {

                chart.hovering = false;

                chart.setActiveElements([]);
                chart.tooltip.setActiveElements([], { x: 0, y: 0 });

                chart.update();
            };
        });
    }
};
Chart.register(htmlLegendPlugin);

let sortState = 'default';

function renderStatisticsTable(labels, data) {
    const $tableHeader = $('#statistics-table-header');
    const $tableBody = $('#statistics-table-body');

    let sortIndicator = '';
    let displayLabels = labels;
    let displayValues = data;

    switch(sortState) {
        case 'ascending':
            sortIndicator = '↑';
            const sortedAsc = sortDataAsc(labels, data);
            displayLabels = sortedAsc.labels;
            displayValues = sortedAsc.values;
            break;
        case 'descending':
            sortIndicator = '↓';
            const sortedDesc = sortDataDesc(labels, data);
            displayLabels = sortedDesc.labels;
            displayValues = sortedDesc.values;
            break;
        case 'default':
        default:
            sortIndicator = '↻';
    }

    $tableHeader.html(`
        <tr>
            <th class="sortable-header">
                Catégorie <span class="sort-indicator">${sortIndicator}</span>
            </th>
            <th>Durée</th>
        </tr>
    `);

    let rows = '';
    displayLabels.forEach((label, index) => {
        const value = displayValues[index];
        const formattedValue = window.durationConverter(value, 'h min s');
        rows += `
            <tr>
                <td>${label}</td>
                <td>${formattedValue}</td>
            </tr>
        `;
    });

    $tableBody.html(rows);

    $('.sortable-header').off('click').on('click', function() {
        switch(sortState) {
            case 'default': sortState = 'ascending'; break;
            case 'ascending': sortState = 'descending'; break;
            case 'descending': sortState = 'default'; break;
        }
        renderStatisticsTable(labels, data);
    });
}

function sortDataAsc(labels, data) {
    const combined = labels.map((label, index) => ({
        label: label,
        value: data[index]
    }));

    combined.sort((a, b) => a.label.localeCompare(b.label));

    return {
        labels: combined.map(item => item.label),
        values: combined.map(item => item.value)
    };
}

function sortDataDesc(labels, data) {
    const combined = labels.map((label, index) => ({
        label: label,
        value: data[index]
    }));

    combined.sort((a, b) => b.label.localeCompare(a.label));

    return {
        labels: combined.map(item => item.label),
        values: combined.map(item => item.value)
    };
}


function downloadStatisticsPDF() {
    if (!currentStatisticData.labels || currentStatisticData.labels.length === 0) {
        alert('Aucune statistique à exporter');
        return;
    }

    if (typeof html2pdf === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js';
        script.onload = function() {
            generatePDF();
        };
        script.onerror = function() {
            alert('Erreur de chargement de html2pdf. Veuillez réessayer.');
        };
        document.head.appendChild(script);
    } else {
        generatePDF();
    }

    function generatePDF() {
        // Créer un conteneur invisible hors écran
        const pdfContainer = document.createElement('div');
        pdfContainer.id = 'temp-pdf-container';
        pdfContainer.style.position = 'absolute';
        pdfContainer.style.left = '-10000px';
        pdfContainer.style.top = '0';
        pdfContainer.style.zIndex = '-1';

        // Contenu du PDF
        const pdfContent = document.createElement('div');
        pdfContent.className = 'pdf-content';
        pdfContent.style.padding = '20px';
        pdfContent.style.maxWidth = '1200px';
        pdfContent.style.background = 'white';
        pdfContent.style.fontFamily = 'Arial, sans-serif';

        // Titre
        const title = document.createElement('h2');
        title.textContent = currentStatisticData.name;
        title.style.textAlign = 'center';
        title.style.marginBottom = '20px';
        pdfContent.appendChild(title);

        // Info
        const infoDiv = document.createElement('div');
        infoDiv.style.marginBottom = '20px';
        infoDiv.innerHTML = `
            <p><strong>Description:</strong> ${currentStatisticData.description}</p>
            <p><strong>Date:</strong> ${currentStatisticData.date}</p>
        `;
        pdfContent.appendChild(infoDiv);

        // Conteneur pour table au-dessus, graphique en dessous
        const contentContainer = document.createElement('div');
        contentContainer.style.marginTop = '20px';

        // Table container (100% width)
        const tableContainer = document.createElement('div');
        tableContainer.style.width = '100%';
        tableContainer.style.marginBottom = '20px';
        tableContainer.appendChild(document.getElementById('statistics-data-table').cloneNode(true));
        contentContainer.appendChild(tableContainer);

        // Graph container (100% width)
        const graphContainer = document.createElement('div');
        graphContainer.style.width = '100%';
        
        // Image du graphique + légende (uniquement si on a un chart à afficher)
        let img = null;
        if (currentStatisticData.graphType !== 'table') {
            img = document.createElement('img');
            img.src = document.getElementById('statisticsPie').toDataURL('image/png');
            img.style.width = '100%';
            img.style.maxHeight = '350px';
            graphContainer.appendChild(img);
            
            // Légende
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

        // Attendre que l'image soit chargée (uniquement si img existe)
        if (img) {
            img.onload = function() {
                generatePDFFromElement();
            };
            
            // Si l'image est déjà chargée
            if (img.complete) {
                generatePDFFromElement();
            }
        } else {
            // Pas d'image (type = table), générer directement
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

function initStatisticsChart(labels, data, type = 'pie') {
    const colors = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
        '#FF9F40', '#C9CBCF', '#66FF66', '#66CCFF', '#FFCC99',
        '#FF33AA', '#33FF99', '#FF66CC', '#66FFFF', '#FF9966'
    ];

    // Détruire l'ancien chart s'il existe
    if (windowStatisticsChart) {
        windowStatisticsChart.destroy();
        windowStatisticsChart = null;
    }

    const canvas = document.getElementById('statisticsPie');
    canvas.style.height = '350px';
    canvas.style.width = '100%';
    
    const ctx = canvas.getContext('2d');

    // Configuration de base
    const baseConfig = {
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors.slice(0, labels.length),
                borderColor: colors.slice(0, labels.length),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.raw;
                            return window.durationConverter(value, 'h min s');
                        }
                    }
                }
            }
        }
    };

    // Configuration spécifique selon le type
    let config = {...baseConfig};

    if (type === 'bar') {
        config.type = 'bar';
        config.options.scales = {
            y: {
                beginAtZero: true,
                ticks: {
                    callback: function(value) {
                        return window.durationConverter(value, 'h min s');
                    }
                }
            },
            x: {
                grid: {
                    display: false
                }
            }
        };
    } else if (type === 'line') {
        config.type = 'line';
        config.options.scales = {
            y: {
                beginAtZero: true,
                ticks: {
                    callback: function(value) {
                        return window.durationConverter(value, 'h min s');
                    }
                }
            },
            x: {
                grid: {
                    display: false
                }
            }
        };
    } else {
        // pie par défaut
        config.type = 'pie';
    }

    windowStatisticsChart = new Chart(ctx, config);
}