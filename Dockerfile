# Oficjalny obraz Playwrighta (Python + przeglądarki + zależności systemowe)
FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

# Katalog roboczy w kontenerze
WORKDIR /app

# Najpierw zależności Pythona
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Potem reszta kodu
COPY . .

# Start: 1 worker gunicorna, żeby nie odpalać 5 instancji Playwrighta naraz
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers=1"]
