from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from analysis.budget_guard import evaluate_budget_risk
from analysis.free_agent_finder import find_bargains
from analysis.lineup_optimizer import (
    Scorer,
    competition_multiplier,
    market_average_ratio,
    optimize_lineup,
    recommended_max_bid,
    weakest_score_by_position,
)
from analysis.market_intelligence import estimate_rival_balances, price_trends
from config import BIWENGER_USER_ID
from db.database import get_connection
from ui_style import empty_state, header, inject_style, money

inject_style()
header("Mercado")

with get_connection() as conn:
    latest_market_date = pd.read_sql_query("SELECT MAX(snapshot_date) AS d FROM market_listings", conn)["d"].iloc[0]
    latest_squad_date = pd.read_sql_query("SELECT MAX(snapshot_date) AS d FROM squad_ownership", conn)["d"].iloc[0]

    scorer = Scorer(conn)
    market_rows = conn.execute(
        """
        SELECT m.player_id, p.name, t.name, p.position, p.status, p.team_id,
               p.points_avg_blended, p.games_played, p.rounds_available, p.points_last_season_blended,
               m.price, m.my_bid_amount,
               CASE
                   WHEN m.seller_user_id IS NULL THEN 'Libre'
                   WHEN m.seller_user_id = ? THEN 'Tú'
                   ELSE lu.name
               END
        FROM market_listings m
        JOIN players p ON p.id = m.player_id
        LEFT JOIN teams t ON t.id = p.team_id
        LEFT JOIN league_users lu ON lu.id = m.seller_user_id
        WHERE m.snapshot_date = ? AND p.team_id IS NOT NULL
        """,
        (BIWENGER_USER_ID, latest_market_date),
    ).fetchall()
    market_bargain_ids = {b["player_id"] for b in find_bargains(conn, top_n=40, only_free_agents=False)}

    scored_market = []
    for player_id, name, team_name, position, status, team_id, pab, gp, ra, pls, price, my_bid, en_venta_por in market_rows:
        entry = scorer.score(player_id, name, position, status, team_id, pab, gp, ra, pls)
        entry.update(
            {
                "team": team_name, "price": price, "my_bid": my_bid,
                "en_venta_por": en_venta_por, "es_ganga": player_id in market_bargain_ids,
            }
        )
        scored_market.append(entry)

    avg_market_ratio = market_average_ratio(scored_market)
    lineup = optimize_lineup(conn, BIWENGER_USER_ID) if latest_squad_date else None
    weakest_by_pos, gap_positions = weakest_score_by_position(lineup)
    budget_risk = evaluate_budget_risk(conn, BIWENGER_USER_ID)
    maximum_bid = budget_risk["maximum_bid"] if budget_risk else None
    competition_mult = competition_multiplier(estimate_rival_balances(conn, BIWENGER_USER_ID))

    for e in scored_market:
        e["puja_recomendada"] = (
            None if e["en_venta_por"] == "Tú"
            else recommended_max_bid(
                e["score"], e["position"], e["price"], weakest_by_pos, gap_positions,
                e["es_ganga"], avg_market_ratio, maximum_bid, competition_mult,
            )
        )

    market_df = pd.DataFrame(
        [
            {
                "Posición": e["position"],
                "Jugador": f"🔥 {e['name']}" if e["es_ganga"] else e["name"],
                "Equipo": e["team"],
                "Puntuación": e["score"],
                "Precio de Mercado": e["price"],
                "Puja Máxima Recomendada": e["puja_recomendada"],
                "Mi Puja": e["my_bid"],
                "En Venta Por": e["en_venta_por"],
            }
            for e in scored_market
        ]
    ).sort_values("Puntuación", ascending=False)
    market_df["Precio de Mercado"] = market_df["Precio de Mercado"].apply(money)
    market_df["Puja Máxima Recomendada"] = market_df["Puja Máxima Recomendada"].apply(
        lambda v: money(v) if pd.notna(v) else "—"
    )
    market_df["Mi Puja"] = market_df["Mi Puja"].apply(lambda v: money(v) if pd.notna(v) else "—")

tab_hoy, tab_gangas, tab_inteligencia = st.tabs(["En venta hoy", "Gangas Libres", "Inteligencia de Mercado"])

with tab_hoy:
    if budget_risk and (budget_risk["deficit_after_listed_sales"] > 0 or budget_risk["deficit_now"] > 0):
        deadline = ""
        if budget_risk["round_ends_at"]:
            ends = datetime.fromtimestamp(budget_risk["round_ends_at"], tz=timezone.utc).astimezone()
            deadline = f" antes de que acabe {budget_risk['round_name']} ({ends.strftime('%d/%m %H:%M')})"

        with st.expander("⚠️ Riesgo de saldo negativo", expanded=True):
            if budget_risk["deficit_after_listed_sales"] > 0:
                st.warning(
                    f"Aun contando con el saldo futuro de tus {money(budget_risk['pending_own_sales_total'])} en "
                    f"jugadores ya listados en venta (saldo proyectado {money(budget_risk['projected_balance'])}), "
                    f"tus pujas activas ({money(budget_risk['committed_bids'])}) te dejarían en negativo por "
                    f"{money(budget_risk['deficit_after_listed_sales'])}. Necesitas vender más{deadline}."
                )
                st.caption("Sugerencia de venta adicional (peor relación rendimiento/precio primero):")
                suggestions_df = pd.DataFrame(budget_risk["sale_suggestions"])[
                    ["name", "price", "score", "cumulative_total"]
                ].rename(
                    columns={
                        "name": "Jugador", "price": "Valor",
                        "score": "Puntuación", "cumulative_total": "Total Acumulado",
                    }
                )
                suggestions_df["Valor"] = suggestions_df["Valor"].apply(money)
                suggestions_df["Total Acumulado"] = suggestions_df["Total Acumulado"].apply(money)
                st.dataframe(suggestions_df, use_container_width=True, hide_index=True)
            else:
                st.info(
                    f"Ahora mismo tus pujas activas ({money(budget_risk['committed_bids'])}) superan tu saldo "
                    f"líquido ({money(budget_risk['balance'])}), pero tus "
                    f"{money(budget_risk['pending_own_sales_total'])} en jugadores ya listados en venta deberían "
                    f"cubrir el hueco (saldo proyectado {money(budget_risk['projected_balance'])}) si se "
                    f"venden{deadline}."
                )

    if latest_market_date:
        if budget_risk:
            saldo_futuro = (
                budget_risk["balance"] + budget_risk["pending_own_sales_total"] - budget_risk["committed_bids"]
            )
            m1, m2, m3 = st.columns(3)
            m1.metric("Saldo actual", money(budget_risk["balance"]))
            m2.metric(
                "Saldo futuro",
                money(saldo_futuro),
                delta=money(saldo_futuro - budget_risk["balance"]),
                help=(
                    f"Saldo actual ({money(budget_risk['balance'])}) + tus ventas listadas "
                    f"({money(budget_risk['pending_own_sales_total'])}) - tus pujas activas "
                    f"({money(budget_risk['committed_bids'])}), si todas se resuelven a tu favor."
                ),
            )
            m3.metric("Puja máxima permitida", money(budget_risk["maximum_bid"]))
            st.caption(
                f"Saldo futuro = saldo actual + ventas listadas ({money(budget_risk['pending_own_sales_total'])}) "
                f"− pujas activas ({money(budget_risk['committed_bids'])})."
            )
        st.caption(
            "🔥 = está entre los jugadores con mejor relación rendimiento/precio de toda la liga "
            "(mismo criterio que Gangas Libres). Puja máxima recomendada = lo que tiene sentido ofrecer según "
            "su rendimiento (comparado con lo que se paga de media en el mercado ahora mismo), si tu equipo lo "
            "necesita en esa posición, si ya es una ganga y cuánta presión de puja hay en la liga (saldo "
            "estimado de los demás managers) — nunca por debajo del precio de mercado ni por encima de tu "
            "puja máxima permitida."
        )
        st.dataframe(market_df, use_container_width=True, hide_index=True)
    else:
        empty_state("Todavía no hay datos de mercado.")

with tab_gangas:
    if not latest_squad_date:
        empty_state("Todavía no hay datos de plantilla.")
    else:
        st.caption(
            "Jugadores libres (misma fórmula que el 11 ideal: puntos fantasy + calidad real de SofaScore + "
            "rival + consistencia). Solo titulares reales — prioriza minutos reales jugados según SofaScore "
            "sobre cualquier predicción o proxy."
        )
        posicion_filtro = st.selectbox("Posición", ["Todas", "PT", "DF", "MC", "DL"])
        with get_connection() as conn:
            bargains = find_bargains(conn, top_n=40, position=None if posicion_filtro == "Todas" else posicion_filtro)
        for b in bargains:
            b["puja_recomendada"] = recommended_max_bid(
                b["score"], b["position"], b["price"], weakest_by_pos, gap_positions,
                True, avg_market_ratio, maximum_bid, competition_mult,
            )

        def _format_bargains(rows, sort_key):
            df = pd.DataFrame(rows).sort_values(sort_key, ascending=False)
            df["jugador"] = df.apply(lambda r: f"🔒 {r['name']}" if r["consistente"] else r["name"], axis=1)
            df["price"] = df["price"].apply(money)
            df["puja_recomendada"] = df["puja_recomendada"].apply(money)
            return df[
                ["position", "jugador", "team", "price", "puja_recomendada", "titularidad_note", "score", "ratio"]
            ].rename(
                columns={
                    "position": "Posición", "jugador": "Jugador", "team": "Equipo", "price": "Valor",
                    "puja_recomendada": "Puja Máxima Recomendada",
                    "titularidad_note": "Titularidad", "score": "Puntuación", "ratio": "Puntos por Millón",
                }
            )

        st.caption(
            "🔒 = titularidad prácticamente asegurada (≥90%), con bonus por su potencial ofensivo. Puja máxima "
            "recomendada = lo que tiene sentido ofrecer según su rendimiento, si tu equipo lo necesita en esa "
            "posición y la presión de puja de la liga — nunca por debajo del precio de mercado ni por encima "
            "de tu puja máxima permitida."
        )
        sub_caras, sub_baratas = st.tabs(["Gangas caras", "Gangas baratas"])

        with sub_caras:
            st.caption("Los que más puntúan — el mayor aporte para tu 11 ideal, sin mirar el precio.")
            st.dataframe(_format_bargains(bargains, "score").head(20), use_container_width=True, hide_index=True)

        with sub_baratas:
            st.caption("Mejor relación puntos/precio — los chollos más rentables por cada millón invertido.")
            st.dataframe(_format_bargains(bargains, "ratio").head(20), use_container_width=True, hide_index=True)

with tab_inteligencia:
    if not latest_squad_date:
        empty_state("Todavía no hay datos de plantilla.")
    else:
        st.subheader("Especulación")
        with get_connection() as conn:
            trends = price_trends(conn, top_n=15)
            trend_scorer = Scorer(conn)
            for t in trends:
                row = conn.execute(
                    "SELECT status, team_id, points_avg_blended, games_played, rounds_available, "
                    "points_last_season_blended FROM players WHERE id = ?",
                    (t["player_id"],),
                ).fetchone()
                status, team_id, pab, gp, ra, pls = row
                t["puntuación"] = trend_scorer.score(t["player_id"], t["name"], t["position"], status, team_id, pab, gp, ra, pls)["score"]
        if trends:
            first = trends[0]
            if first["days_tracked"] <= 1:
                st.caption(
                    "Solo hay un día de histórico de precios todavía, así que la tendencia usa el incremento "
                    "diario que ya calcula Biwenger. En cuanto `fetch_data.py` lleve varios días ejecutándose, "
                    "esto pasará a usar la variación real de varios días."
                )
            else:
                st.caption(f"Tendencia calculada sobre {first['days_tracked']} días de histórico.")
            trends_df = pd.DataFrame(trends).sort_values("puntuación", ascending=False)
            trends_df["price"] = trends_df["price"].apply(money)
            trends_df["price_increment_day"] = trends_df["price_increment_day"].apply(money)
            trends_df = trends_df[["position", "name", "price", "puntuación", "trend_pct", "price_increment_day"]].rename(
                columns={
                    "position": "Posición", "name": "Jugador", "price": "Valor", "puntuación": "Puntuación",
                    "trend_pct": "Tendencia %", "price_increment_day": "Incremento Hoy",
                }
            )
            st.dataframe(trends_df, use_container_width=True, hide_index=True)
        else:
            st.info("No hay candidatos con datos suficientes todavía.")

        st.subheader("Saldo estimado de los managers")
        with get_connection() as conn:
            rivals = estimate_rival_balances(conn, BIWENGER_USER_ID)
        if rivals:
            st.caption(
                f"Estimación, no un dato oficial (Biwenger solo expone tu propio saldo). Calculada asumiendo que "
                f"todos empezaron con el mismo presupuesto (≈{money(rivals['estimated_starting_balance'])}) y "
                f"sumando las compras/ventas registradas en el histórico de la liga — no incluye el reparto "
                f"inicial de plantillas ni ajustes que no dejen rastro."
            )
            rivals_df = pd.DataFrame(rivals["managers"])
            rivals_df["manager"] = rivals_df.apply(lambda r: f"{r['name']} (tú)" if r["is_self"] else r["name"], axis=1)
            rivals_df["estimated_balance"] = rivals_df["estimated_balance"].apply(money)
            rivals_df["squad_value"] = rivals_df["squad_value"].apply(money)
            rivals_df = rivals_df[["manager", "estimated_balance", "squad_value"]].rename(
                columns={
                    "manager": "Manager", "estimated_balance": "Saldo Estimado", "squad_value": "Valor de Plantilla",
                }
            )
            st.dataframe(rivals_df, use_container_width=True, hide_index=True)
        else:
            st.info("No hay datos suficientes todavía.")
