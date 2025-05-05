web: gunicorn app:app -w 1 -k gthread --timeout 120
web: uvicorn app:app --host=0.0.0.0 --port=10000 --workers=1
