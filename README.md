# Biwenger IA

Asistente de manager inteligente para Biwenger: extrae datos reales de tu liga, los guarda en SQLite
con histórico, y añade un optimizador de 11 ideal, buscador de gangas e inteligencia de mercado.

## Puesta en marcha (local)

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # y rellena BIWENGER_TOKEN, BIWENGER_LEAGUE_ID, BIWENGER_USER_ID
python scripts\fetch_data.py
streamlit run app\streamlit_app.py
```

## Estructura

- `config.py` — carga variables de entorno
- `db/` — esquema SQLite y helpers de acceso
- `biwenger_client/` — cliente de la API (no oficial) de Biwenger
- `sofascore_client/` — cliente de la API (no oficial) de SofaScore
- `analysis/` — optimizador de 11 ideal, gangas, sustituciones, inteligencia de mercado
- `scripts/fetch_data.py` — extrae datos y los guarda en `data/biwenger.db`
- `app/streamlit_app.py` — app de Streamlit (Mi Equipo, Mercado)
- `tests/` — tests del modelo de puntuación (`pytest`)

## Despliegue en Render.com (acceso restringido a ti)

La app usa `st.login`/`st.user` de Streamlit (login con Google vía OIDC) para que solo tu
cuenta pueda entrar cuando está desplegada. En local, si no defines `ALLOWED_EMAIL`, no pide
login — se usa igual que hasta ahora.

### 1. Google Cloud — credenciales OAuth

1. Ve a [Google Cloud Console](https://console.cloud.google.com/) → crea (o reutiliza) un proyecto.
2. **APIs y servicios → Pantalla de consentimiento OAuth**: tipo *Externo*, en modo *Testing*, y
   añádete a ti mismo como *test user* con tu email de Google.
3. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**, tipo
   *Aplicación web*. En "URIs de redirección autorizados" añade:
   - `http://localhost:8501/oauth2callback` (para probar en local)
   - `https://<nombre-de-tu-app>.onrender.com/oauth2callback` (decide ya el nombre que le
     pondrás al servicio en Render, el paso 3 usa esta misma URL)
4. Guarda el `Client ID` y el `Client secret` que te da Google.

### 2. GitHub

Render despliega desde un repositorio git. Crea un repositorio **privado** en GitHub y súbelo:

```powershell
git init
git add .
git commit -m "Deploy inicial"
git branch -M main
git remote add origin https://github.com/<tu-usuario>/biwenger-ia.git
git push -u origin main
```

### 3. Render — crear el servicio

1. En [Render](https://render.com), **New → Web Service**, conecta el repo de GitHub.
2. Nombre del servicio: el mismo que usaste en la URI de redirección de Google (paso 1).
3. Build command: `pip install -r requirements.txt`
4. Start command: `streamlit run app/streamlit_app.py --server.port $PORT --server.address 0.0.0.0`
5. Plan: *Free* (con el plan free, el disco se borra en cada reinicio — ver más abajo).
6. En **Environment**, añade estas variables:
   - `BIWENGER_TOKEN`, `BIWENGER_LEAGUE_ID`, `BIWENGER_USER_ID` (las mismas de tu `.env`)
   - `ALLOWED_EMAIL` = tu email de Google (el mismo que añadiste como test user)
7. En **Secret Files**, añade un archivo con ruta `.streamlit/secrets.toml` (plantilla en
   `.streamlit/secrets.toml.example` de este repo) con:
   ```toml
   [auth]
   redirect_uri = "https://<nombre-de-tu-app>.onrender.com/oauth2callback"
   cookie_secret = "..."   # genera uno con: python -c "import secrets; print(secrets.token_hex(32))"

   [auth.google]
   client_id = "..."
   client_secret = "..."
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```
8. Deploy. La primera vez tendrás que entrar y pulsar el botón de refrescar (🔄, arriba a la
   derecha) para poblar la base de datos, ya que empieza vacía.

### Nota sobre persistencia

El plan Free de Render no tiene disco persistente: cada vez que el servicio se reinicia
(se apaga solo tras ~15 min sin uso) se borra `data/biwenger.db` y hay que volver a pulsar
"Actualizar datos". El histórico de precios (pestaña Especulación) no llega a acumularse de
un día para otro en ese plan. Si quieres que los datos sobrevivan a reinicios, necesitas un
plan de pago (Starter o superior) con un **disco persistente** añadido y apuntar `DB_PATH`
(en `config.py`) a una ruta dentro de ese disco.
