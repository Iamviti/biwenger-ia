from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from analysis.lineup_optimizer import CANDIDATE_FORMATIONS, Scorer, optimize_lineup
from analysis.squad_upgrades import find_squad_upgrades
from config import BIWENGER_USER_ID
from db.database import get_connection
from ui_pitch import render_pitch
from ui_style import empty_state, header, inject_style, money

inject_style()
header("Mi Equipo")

with get_connection() as conn:
    latest_squad_date = pd.read_sql_query("SELECT MAX(snapshot_date) AS d FROM squad_ownership", conn)["d"].iloc[0]
    lineup = optimize_lineup(conn, BIWENGER_USER_ID) if latest_squad_date else None

    position_counts = dict(
        conn.execute(
            """
            SELECT p.position, COUNT(*) FROM squad_ownership s
            JOIN players p ON p.id = s.player_id
            WHERE s.snapshot_date = ? AND s.league_user_id = ? AND p.team_id IS NOT NULL
              AND p.id NOT IN (
                  SELECT player_id FROM market_listings
                  WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM market_listings) AND seller_user_id = ?
              )
            GROUP BY p.position
            """,
            (latest_squad_date, BIWENGER_USER_ID, BIWENGER_USER_ID),
        ).fetchall()
    )
    total_players = sum(position_counts.values())

    squad_scorer = Scorer(conn)
    squad_rows = conn.execute(
        """
        SELECT p.id, p.name, p.position, p.status, p.status_info, p.team_id,
               p.points_avg_blended, p.games_played, p.rounds_available, p.points_last_season_blended,
               pp.amount, p.price
        FROM squad_ownership s
        JOIN players p ON p.id = s.player_id
        LEFT JOIN player_purchases pp ON pp.player_id = s.player_id
        WHERE s.snapshot_date = ? AND s.league_user_id = ? AND p.team_id IS NOT NULL
          AND p.id NOT IN (
              SELECT player_id FROM market_listings
              WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM market_listings) AND seller_user_id = ?
          )
        """,
        (latest_squad_date, BIWENGER_USER_ID, BIWENGER_USER_ID),
    ).fetchall()

    squad_rows_data = []
    for player_id, name, position, status, status_info, team_id, pab, gp, ra, pls, precio_compra, valor_actual in squad_rows:
        entry = squad_scorer.score(player_id, name, position, status, team_id, pab, gp, ra, pls)
        squad_rows_data.append(
            {
                "posición": position,
                "jugador": name,
                "estado": status if status != "ok" else "—",
                "estado_info": status_info or "—",
                "precio_compra": precio_compra,
                "valor_actual": valor_actual,
                "plusvalia": (valor_actual - precio_compra) if precio_compra is not None else None,
                "rating_sofascore": entry["avg_rating"],
                "minutos_sofascore": entry["avg_minutes"],
                "puntuación": entry["score"],
            }
        )
    squad_df = pd.DataFrame(
        squad_rows_data,
        columns=[
            "posición", "jugador", "estado", "estado_info", "precio_compra", "valor_actual", "plusvalia",
            "rating_sofascore", "minutos_sofascore", "puntuación",
        ],
    ).sort_values("puntuación", ascending=False)

    squad_upgrades = find_squad_upgrades(conn, BIWENGER_USER_ID) if latest_squad_date else []

FORMATION_NAMES = list(CANDIDATE_FORMATIONS.keys())


def _with_fecha(players):
    df = pd.DataFrame(players)[
        ["position", "name", "status", "rival", "kickoff_at", "games_played", "rounds_available",
         "avg_rating", "avg_minutes", "titularidad_note", "score"]
    ]
    df["kickoff_at"] = df["kickoff_at"].apply(
        lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%d/%m") if ts else "—"
    )
    df["partidos"] = df["games_played"].astype(str) + "/" + df["rounds_available"].astype(str)
    df["avg_rating"] = df["avg_rating"].apply(lambda v: v if pd.notna(v) else "—")
    df["avg_minutes"] = df["avg_minutes"].apply(lambda v: f"{v:.0f}" if pd.notna(v) else "—")
    return df[
        ["position", "name", "status", "rival", "kickoff_at", "partidos", "avg_rating", "avg_minutes",
         "titularidad_note", "score"]
    ].rename(
        columns={
            "position": "posición", "name": "jugador", "status": "estado", "rival": "rival",
            "kickoff_at": "fecha", "avg_rating": "rating_sofascore", "avg_minutes": "min_reales",
            "titularidad_note": "titularidad", "score": "puntuación",
        }
    )


if not latest_squad_date:
    empty_state("Todavía no hay datos de plantilla.")
else:
    tab_plantilla, tab_once, tab_sustituciones = st.tabs(["Mi Plantilla", "Once Ideal", "Posibles Sustituciones"])

    with tab_once:
        if not lineup["feasible"]:
            st.warning(lineup["reason"])

            best_by_name = lineup["best_effort_options"]
            ranked = sorted(best_by_name.values(), key=lambda a: -a["total_score"])
            st.info(
                f"📊 Con lo que tienes disponible ahora mismo, **{ranked[0]['formation']}** tiene más potencial de "
                f"puntos ({ranked[0]['total_score']}) que **{ranked[1]['formation']}** ({ranked[1]['total_score']}) "
                f"— orientativo, ninguna de las dos está completa todavía."
            )

            chosen = st.radio(
                "Formación", FORMATION_NAMES,
                index=FORMATION_NAMES.index(lineup["best_effort"]["formation"]),
                horizontal=True, key="formation_toggle_infeasible",
            )
            best_effort = best_by_name[chosen]
            st.caption(
                f"Esquema {best_effort['formation']} con lo que tienes disponible ahora mismo — "
                f"los huecos marcados con \"?\" son las posiciones que te faltan por cubrir "
                f"({best_effort['empty_count']} hueco{'s' if best_effort['empty_count'] != 1 else ''})."
            )
            render_pitch(best_effort["starters"])

            st.caption(f"Mejores opciones del mercado de hoy para completar {chosen} (dentro de tu puja máxima):")
            fill_suggestions = lineup["market_fill_suggestions_by_formation"][chosen]
            if not fill_suggestions:
                st.caption(f"No te falta nadie para completar {chosen} con lo que tienes disponible.")
            for pos, info in fill_suggestions.items():
                st.markdown(f"**{pos}** — te faltan {info['faltan']}")
                if info["candidatos"]:
                    fill_df = pd.DataFrame(info["candidatos"])[["name", "score", "price", "titularidad_note"]]
                    fill_df["price"] = fill_df["price"].apply(money)
                    st.dataframe(
                        fill_df.rename(
                            columns={"name": "jugador", "score": "puntuación", "price": "valor", "titularidad_note": "titularidad"}
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("No hay candidatos disponibles en el mercado hoy dentro de tu presupuesto.")
        else:
            otras = [c for c in lineup["formation_comparison"] if c["formation"] != lineup["formation"]]
            if otras and otras[0]["feasible"]:
                st.info(
                    f"📊 Esta jornada, **{lineup['formation']}** tiene más potencial de puntos ({lineup['total_score']}) "
                    f"que **{otras[0]['formation']}** ({otras[0]['total_score']})."
                )
            else:
                st.info(
                    f"📊 Esta jornada juegas con **{lineup['formation']}** ({lineup['total_score']}) — "
                    f"{otras[0]['formation'] if otras else 'la otra formación'} no es viable con tu plantilla actual."
                )
            st.caption("Solo se evalúan tus dos formaciones de la temporada (3-4-3 y 3-5-2).")
            st.caption(
                "Puntuación = puntos fantasy AS+SofaScore de esta temporada (ponderados con la pasada al inicio de "
                "curso) × calidad real de juego (rating de SofaScore vs. la media de la liga) × dificultad del "
                "próximo rival y casa/fuera × titularidad (minutos reales de SofaScore si los hay, si no alineación "
                "prevista, si no tasa de aparición en Biwenger)."
            )

            chosen = st.radio(
                "Formación", FORMATION_NAMES,
                index=FORMATION_NAMES.index(lineup["formation"]),
                horizontal=True, key="formation_toggle",
            )
            selected = lineup["all_formations"][chosen]

            if not selected["feasible"]:
                st.info(selected["reason"])
            else:
                if chosen != lineup["formation"]:
                    st.caption(
                        f"Viendo {chosen} (puntuación {selected['total_score']}) — la recomendada esta jornada es "
                        f"{lineup['formation']} (puntuación {lineup['total_score']})."
                    )

                render_pitch(selected["starters"])
                st.dataframe(_with_fecha(selected["starters"]), use_container_width=True, hide_index=True)
                if any(p["status"] != "ok" for p in selected["starters"]):
                    st.caption("⚠️ Hay titulares con estado distinto de 'ok' (duda/otros) — revísalo antes de confirmar alineación.")
                baja_aparicion = [p["name"] for p in selected["starters"] if p["low_appearance"]]
                if baja_aparicion:
                    st.caption(
                        f"⚠️ Titulares que no juegan con regularidad esta temporada (revisa si son duda de "
                        f"titularidad real): {', '.join(baja_aparicion)}."
                    )

                listed = [p for p in lineup["excluded"] if p.get("reason") == "en venta"]
                if listed:
                    st.caption(f"No se han considerado por estar en venta: {', '.join(p['name'] for p in listed)}.")

                if lineup["sale_warnings"]:
                    nombres = ", ".join(
                        f"{p['name']} ({p['position']}, puntuación {p['score']})" for p in lineup["sale_warnings"]
                    )
                    st.warning(
                        f"⚠️ Si no estuvieran en venta, estos jugadores serían titulares en tu 11 ideal "
                        f"({lineup['formation']}) — valora retirarlos del mercado: {nombres}."
                    )

                if selected["bench"]:
                    st.caption("Banquillo:")
                    st.dataframe(_with_fecha(selected["bench"]), use_container_width=True, hide_index=True)

                if lineup["market_upgrades"]:
                    st.subheader("Posibles fichajes de mejora")
                    st.caption(
                        f"Basado en la formación recomendada ({lineup['formation']}): jugadores del mercado de hoy "
                        f"que superarían a tu titular más débil de su posición y cuyo precio cabe en tu puja "
                        f"máxima permitida."
                    )
                    upgrades_df = pd.DataFrame(lineup["market_upgrades"])[
                        ["position", "out", "out_score", "in", "in_score", "price", "mejora"]
                    ]
                    upgrades_df["price"] = upgrades_df["price"].apply(money)
                    st.dataframe(
                        upgrades_df.rename(
                            columns={
                                "position": "posición", "out": "sale", "out_score": "puntuación_actual",
                                "in": "entra", "in_score": "puntuación_nueva", "price": "precio", "mejora": "mejora",
                            }
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

    with tab_plantilla:
        if "plantilla_pos_filter" not in st.session_state:
            st.session_state["plantilla_pos_filter"] = None

        position_filters = [
            (None, "Total", total_players),
            ("PT", "Portero", position_counts.get("PT", 0)),
            ("DF", "Defensas", position_counts.get("DF", 0)),
            ("MC", "Medios", position_counts.get("MC", 0)),
            ("DL", "Delanteros", position_counts.get("DL", 0)),
        ]
        filter_cols = st.columns(5)
        for col, (pos, label, count) in zip(filter_cols, position_filters):
            is_active = st.session_state["plantilla_pos_filter"] == pos
            if col.button(
                f"{label} · {count}",
                key=f"plantilla_filter_{pos or 'total'}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["plantilla_pos_filter"] = pos
                st.rerun()
        st.caption(
            "No cuenta a los jugadores que ya tienes puestos en venta (igual que la tabla de abajo). "
            "Haz clic en una posición para filtrar."
        )

        active_filter = st.session_state["plantilla_pos_filter"]
        if active_filter:
            squad_df = squad_df[squad_df["posición"] == active_filter]

        squad_df["valor_actual"] = squad_df["valor_actual"].apply(money)
        squad_df[["precio_compra", "plusvalia"]] = squad_df[["precio_compra", "plusvalia"]].apply(
            lambda col: col.map(lambda v: money(v) if pd.notna(v) else "—")
        )
        squad_df["rating_sofascore"] = squad_df["rating_sofascore"].apply(lambda v: v if pd.notna(v) else "—")
        squad_df["minutos_sofascore"] = squad_df["minutos_sofascore"].apply(
            lambda v: f"{v:.0f}" if pd.notna(v) else "—"
        )
        st.caption(
            "No se listan los jugadores que ya tienes puestos en venta. "
            "El precio de compra se reconstruye del historial de fichajes de la liga — los jugadores que llevas "
            "desde el reparto inicial de plantillas no tienen ese registro (Biwenger no lo expone). "
            "Rating y minutos son la media real de SofaScore en sus últimos partidos jugados (no siempre de esta "
            "temporada, si apenas lleva jornadas disputadas). Estado = texto oficial de Biwenger para lesión/duda "
            "(incluye la fecha estimada de vuelta cuando la dan)."
        )
        st.dataframe(
            squad_df.rename(
                columns={
                    "posición": "Posición", "jugador": "Jugador", "estado": "Estado", "estado_info": "Detalle",
                    "precio_compra": "Precio de Compra", "valor_actual": "Valor Actual",
                    "plusvalia": "Plusvalía", "rating_sofascore": "Rating SofaScore",
                    "minutos_sofascore": "Minutos SofaScore", "puntuación": "Puntuación",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    with tab_sustituciones:
        st.caption(
            "Jugadores del mercado de hoy que superan a cada uno de los tuyos a la vez en rendimiento esperado "
            "y en relación rendimiento/precio (no solo en puntuación), y cuyo precio cabe en tu puja máxima "
            "permitida. No se compara al portero suplente."
        )
        if squad_upgrades:
            rows = []
            for u in squad_upgrades:
                pct_txt = f" ({u['mejora_puntos_pct']:+d}%)" if u["mejora_puntos_pct"] is not None else ""
                valor_txt = f"{u['mejora_ratio_pct']:+d}%" if u["mejora_ratio_pct"] is not None else "nuevo"
                rows.append(
                    {
                        "posición": u["position"],
                        "jugador actual": f"{u['out']} · {u['out_score']} pts",
                        "fichaje sugerido": f"{u['in']} · {u['in_score']} pts",
                        "precio": money(u["price"]),
                        "mejora rendimiento": f"+{u['mejora_puntos']} pts{pct_txt}",
                        "mejora calidad/precio": valor_txt,
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("Ningún jugador del mercado de hoy mejora a la vez en rendimiento y en relación rendimiento/precio.")
