from fastapi import APIRouter
from app.services.finetuning_couples import export_finetuning_service

router = APIRouter(prefix="/admin", tags=["admin"]) 
@router.get("/export-finetuning") 
def export_finetuning():
    export_finetuning_service()