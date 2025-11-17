# app.py
import streamlit as st
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from bs4 import BeautifulSoup
import pandas as pd
import time

# ---------------------------
# Selenium driver initializer
# ---------------------------
def init_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(GeckoDriverManager().install())
    driver = webdriver.Firefox(service=service, options=options)
    return driver

# ---------------------------
# Odds scraping function
# ---------------------------
def scrape_matches_elcomparador(url, bookmakers=None, headless=True):
    """
    Scrape match odds from El Comparador for a given URL.
    Returns a DataFrame with columns: ['Match','Bookmaker','Home','Draw','Away','TRJ (%)']
    """
    if bookmakers is None:
        bookmakers = ["bet365", "codere", "williamhill", "bwin", "sportium", "888sport", "marathon", "betsson"]

    driver = init_driver(headless=headless)
    driver.get(url)
    time.sleep(4)
    html = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for match_div in soup.find_all("div", id="fila_evento"):
        teams_div = match_div.find("div", id="celda_evento_partido")
        if not teams_div:
            continue
        match_name = " - ".join([t.strip() for t in teams_div.stripped_strings if "Estadísticas" not in t and "Pronósticos" not in t])
        if match_name == "Evento":
            continue

        cuotas_divs = match_div.find_all("div", id="fila_cuotas")
        if len(cuotas_divs) < 3:
            continue

        def extract_odds(fila):
            cells = fila.find_all("div", id="celda_cuotas")[1:]  # skip first label
            return [cell.get_text(strip=True) if cell.get_text(strip=True) else "-" for cell in cells]

        home_odds = extract_odds(cuotas_divs[0])
        draw_odds = extract_odds(cuotas_divs[1])
        away_odds = extract_odds(cuotas_divs[2])

        for i, bookmaker in enumerate(bookmakers):
            h = home_odds[i] if i < len(home_odds) else "-"
            d = draw_odds[i] if i < len(draw_odds) else "-"
            a = away_odds[i] if i < len(away_odds) else "-"

            # Calculate TRJ %
            try:
                if h != "-" and d != "-" and a != "-":
                    trj = 100 / (1/float(h.replace(",", ".")) + 1/float(d.replace(",", ".")) + 1/float(a.replace(",", ".")))
                    trj = round(trj, 2)
                else:
                    trj = None
            except:
                trj = None

            rows.append({
                "Match": match_name,
                "Bookmaker": bookmaker,
                "Home": h,
                "Draw": d,
                "Away": a,
                "TRJ (%)": trj
            })

    df = pd.DataFrame(rows)
    return df

# ---------------------------
# Streamlit UI
# ---------------------------
def main():
    st.title("📊 Primera División Odds Scraper")

    # Fixed URL for Primera División
    primera_div_url = "http://www.elcomparador.com/futbol/espa%C3%B1a/primeradivision"

    all_bookmakers = ["bet365", "codere", "williamhill", "bwin", "sportium", "888sport", "marathon", "betsson"]
    selected_bookmakers = st.multiselect(
        "Select bookmakers to scrape",
        all_bookmakers,
        default=all_bookmakers
    )

    nb_matches = st.slider("Number of matches to show (top N)", 1, 20, 10)

    if st.button("🔍 Start scraping"):
        with st.spinner("Scraping Primera División odds..."):
            df = scrape_matches_elcomparador(primera_div_url, selected_bookmakers)
            if not df.empty:
                # Limit to top N matches
                match_order = df["Match"].drop_duplicates().tolist()[:nb_matches]
                df = df[df["Match"].isin(match_order)].reset_index(drop=True)

                st.subheader(f"📌 Retrieved Odds (showing top {nb_matches} matches)")
                st.dataframe(df)
            else:
                st.warning("No odds retrieved. Check your connection or try again later.")

if __name__ == "__main__":
    main()
