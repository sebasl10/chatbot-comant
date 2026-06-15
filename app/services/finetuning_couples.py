import json 
import os 
from datetime import datetime 
from fastapi.responses import FileResponse 
from app.services.database import get_db_schema, get_finetuning_couples, get_finetuning_triplets
from app.prompts.recherche import build_recherche_prompt  

EXPORT_DIR = "exports" 
def build_sft_entry(user_message: str, generated_sql: str, user_id: int) -> dict:   
    """Construit un exemple SFT (Supervised Fine-Tuning) à partir d'un couple (message, sql)."""    
    system_prompt = build_recherche_prompt(        
        schema=get_db_schema(),    
        user_id=user_id,    
    ) 
    return {        
        "messages": [            
            {"role": "system",    "content": system_prompt},
            {"role": "user",      "content": user_message}, 
            {"role": "assistant", "content": generated_sql},       
        ]    
    } 

def build_dpo_entry(user_message: str, generated_sql: str, correct_sql: str, user_id: int) -> dict:   
    """Construit un exemple DPO (Direct Preference Optimization) à partir d'un triplet (message, incorrect_sql, correct_sql)."""    
    system_prompt = build_recherche_prompt(        
        schema=get_db_schema(),    
        user_id=user_id,    
    ) 
    return {        
        "prompt": [            
            {"role": "system",    "content": system_prompt},
            {"role": "user",      "content": user_message},       
        ],
        "chosen":  {"role": "assistant", "content": correct_sql},   
        "rejected":  {"role": "assistant", "content": generated_sql},   
    } 

def export_finetuning_service():
    """Exporte les couples (message utilisateur → SQL généré) au format ShareGPT JSONL pour SFT et DPO."""
    # Export SFT 
    rows_sft = get_finetuning_couples()
    sft_total = 0
    sft_filepath = None
    print(rows_sft)

    if rows_sft:
        os.makedirs(f"{EXPORT_DIR}/sft", exist_ok=True)
        sft_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sft_filename = f"finetuning_sft_{sft_timestamp}.jsonl"
        sft_filepath = os.path.join(EXPORT_DIR, "sft", sft_filename)

        with open(sft_filepath, "w", encoding="utf-8") as f:
            for row in rows_sft:
                entry = build_sft_entry(
                    user_message=row["input"],
                    generated_sql=row["label"],
                    user_id=row["user_id"],
                )
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                sft_total += 1

    # Export DPO 
    rows_dpo = get_finetuning_triplets()
    dpo_total = 0
    dpo_filepath = None

    if rows_dpo:
        os.makedirs(f"{EXPORT_DIR}/dpo", exist_ok=True)
        dpo_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dpo_filename = f"finetuning_dpo_{dpo_timestamp}.jsonl"
        dpo_filepath = os.path.join(EXPORT_DIR, "dpo", dpo_filename)

        with open(dpo_filepath, "w", encoding="utf-8") as f:
            for row in rows_dpo:
                entry = build_dpo_entry(
                    user_message=row["input"],
                    generated_sql=row["rejected"],
                    correct_sql = row["chosen"],
                    user_id=row["user_id"],
                )
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                dpo_total += 1

    if not sft_filepath and not dpo_filepath:
        return {"message": "Aucun couple SFT ou DPO trouvé.", "count": 0}
    
    last_filepath = dpo_filepath if dpo_filepath else sft_filepath
    last_filename = os.path.basename(last_filepath)

    return FileResponse(
        path=last_filepath,
        media_type="application/x-ndjson",
        filename=last_filename,
        headers={
            "X-Total-SFT": str(sft_total),
            "X-Total-DPO": str(dpo_total),
        },
    )
    
