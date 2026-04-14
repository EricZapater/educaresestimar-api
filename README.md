# Reservations API

API REST per a la gestió de reserves, franges horàries i tipus de sessió. Construïda amb FastAPI, PostgreSQL i Docker.

## Requisits previs

- [Docker](https://docs.docker.com/get-docker/) instal·lat
- [Docker Compose](https://docs.docker.com/compose/install/) instal·lat (inclòs amb Docker Desktop)

## Arrencada ràpida

1. **Copia el fitxer d'entorn** i ajusta els valors si cal:

   ```bash
   cp .env.example .env
   ```

2. **Arrenca tots els serveis:**

   ```bash
   docker compose up --build
   ```

   Això farà:
   - Arrencar PostgreSQL 16
   - Construir la imatge de l'API
   - Executar les migracions d'Alembic automàticament
   - Servir l'API a `http://localhost:8000`

3. **Documentació automàtica (Swagger UI):**

   👉 [http://localhost:8000/docs](http://localhost:8000/docs)

## Endpoints

### Públics (sense autenticació)

| Mètode | Ruta                    | Descripció                                   |
|--------|-------------------------|----------------------------------------------|
| GET    | `/api/session-types`    | Llista tots els tipus de sessió              |
| GET    | `/api/slots?from=&to=`  | Llista franges disponibles dins el rang       |
| POST   | `/api/reservations`     | Crea una nova reserva                        |

### Protegits (requereixen header `X-API-Key`)

| Mètode | Ruta                       | Descripció                                   |
|--------|----------------------------|----------------------------------------------|
| POST   | `/api/slots`               | Crea una franja horària                      |
| DELETE | `/api/slots/:id`           | Elimina una franja (409 si té reserves)      |
| GET    | `/api/reservations?from=&to=` | Llista reserves amb JOINs                 |
| PATCH  | `/api/reservations/:id`    | Actualitza status i/o slot_id                |

## Migracions

Les migracions s'executen automàticament en arrencar l'API. Per executar-les manualment:

```bash
docker compose exec api alembic upgrade head
```

Per crear una nova migració:

```bash
docker compose exec api alembic revision --autogenerate -m "descripció del canvi"
```

## Aturar i netejar

Aturar els serveis:

```bash
docker compose down
```

Aturar i eliminar volums (esborra les dades de PostgreSQL):

```bash
docker compose down -v
```

## Estructura del projecte

```
├── alembic/                  # Migracions de base de dades
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── app/
│   ├── main.py               # Punt d'entrada FastAPI
│   ├── database.py            # Configuració SQLAlchemy async
│   ├── auth.py                # Autenticació per API Key
│   ├── models/                # Models SQLAlchemy (ORM)
│   ├── routers/               # Endpoints (controllers)
│   └── schemas/               # Schemas Pydantic (DTOs)
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── .env / .env.example
└── requirements.txt
```
