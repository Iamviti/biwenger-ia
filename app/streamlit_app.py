import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from config import ALLOWED_EMAIL

st.set_page_config(page_title="Biwenger IA", page_icon="📊", layout="wide")

# Login con Google solo si ALLOWED_EMAIL está configurado (desplegado en Render) — en
# local, sin esa variable, no exige login para no meter fricción en el desarrollo.
if ALLOWED_EMAIL:
    if not st.user.is_logged_in:
        st.title("Biwenger IA")
        st.write("Acceso restringido. Inicia sesión con tu cuenta de Google para continuar.")
        st.button("Iniciar sesión con Google", on_click=st.login, args=("google",))
        st.stop()

    if st.user.email != ALLOWED_EMAIL:
        st.error(f"No autorizado ({st.user.email}).")
        st.button("Cerrar sesión", on_click=st.logout)
        st.stop()

    st.sidebar.caption(f"Sesión: {st.user.email}")
    st.sidebar.button("Cerrar sesión", on_click=st.logout)

mi_equipo = st.Page("views/mi_equipo.py", title="Mi Equipo", url_path="mi-equipo", default=True)
mercado = st.Page("views/mercado.py", title="Mercado", url_path="mercado")

pg = st.navigation([mi_equipo, mercado])
pg.run()
