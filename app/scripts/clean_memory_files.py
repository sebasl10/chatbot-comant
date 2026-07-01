#!/usr/bin/env python3
"""
Script pour nettoyer les fichiers de mémoire en utilisant le LLM.

Ce script doit être lancé manuellement avec la commande :
    python app/scripts/clean_memory_files.py

Il va :
1. Lire tous les fichiers .md dans le dossier app/memory/ (tous les sous-dossiers)
2. Pour chaque fichier, appeler le LLM avec le prompt de nettoyage
3. Réécrire les fichiers avec les modifications du LLM
"""

import os
import sys
import asyncio

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.prompts.memory_cleanup import MEMORY_CLEANUP_PROMPT
from app.services.ollama import call_ollama


async def clean_memory_file(filepath: str) -> bool:
    """
    Nettoie un fichier de mémoire unique en utilisant le LLM.
    
    Args:
        filepath: Chemin vers le fichier .md à nettoyer
        
    Returns:
        True si le fichier a été modifié, False sinon
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if not content.strip():
        print(f"  -> Fichier vide, ignoré: {filepath}")
        return False
    
    user_prompt = f"Contenu du fichier de mémoire à nettoyer :\n\n{content}"
    print(f"  -> Appel du LLM pour nettoyer: {filepath}")
    
    try:
        cleaned_content = await call_ollama(prompt=user_prompt, system=MEMORY_CLEANUP_PROMPT)
        cleaned_content = cleaned_content.strip()

        if cleaned_content.startswith('```') and cleaned_content.endswith('```'):
            cleaned_content = cleaned_content[3:-3].strip()
        
        if cleaned_content.startswith('```markdown'):
            cleaned_content = cleaned_content[11:].strip()
            if cleaned_content.startswith('```'):
                cleaned_content = cleaned_content[3:].strip()
        
        if cleaned_content == content:
            print(f"  -> Aucune modification: {filepath}")
            return False
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        
        print(f"  -> Fichier nettoyé et sauvegardé: {filepath}")
        return True
        
    except Exception as e:
        print(f"  -> Erreur lors du traitement de {filepath}: {e}")
        return False


async def clean_all_memory_files():
    """
    Nettoie tous les fichiers de mémoire dans le dossier app/memory/.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    memory_dir = os.path.join(project_root, "app", "memory")
    
    if not os.path.exists(memory_dir):
        print(f"Dossier non trouvé: {memory_dir}")
        return
    
    cleaned_count = 0
    total_count = 0
    
    for root, dirs, files in os.walk(memory_dir):
        for file in files:
            if file.endswith('.md'):
                filepath = os.path.join(root, file)
                total_count += 1
                print(f"\nTraitement du fichier {total_count}: {filepath}")
                
                if await clean_memory_file(filepath):
                    cleaned_count += 1
    
    print(f"\n{'='*60}")
    print(f"Nettoyage terminé!")
    print(f"Fichiers traités: {total_count}")
    print(f"Fichiers modifiés: {cleaned_count}")
    print(f"{'='*60}")


def main():
    """
    Point d'entrée du script.
    """
    print("="*60)
    print("DEBUT DU NETTOYAGE DES FICHIERS DE MEMOIRE")
    print("="*60)
    
    # Exécuter la fonction async de manière synchrone
    asyncio.run(clean_all_memory_files())


if __name__ == "__main__":
    main()
