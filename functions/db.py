import firebase_admin
from firebase_admin import firestore

_db = None

def getdb():
    global _db
    if _db is None:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        _db = firestore.client()
    return _db
