from datetime import datetime
# from firebase_admin import initialize_app, firestore
# initialize_app()
# db = firestore.client()
from db import getdb


def health_check():
    try:
        db = getdb()
        db.collection("_health").document("ping").set({
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "status": "ok",
            "service": "imdb-scraper-api",
            "timestamp": datetime.utcnow().isoformat()
        }, 200
    
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }, 500    
