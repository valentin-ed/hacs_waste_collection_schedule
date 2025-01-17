# https://data.angers.fr/api/explore/v2.1/catalog/datasets/secteurs-de-collecte-tri-et-plus/records?select=id_secteur&where=typvoie%3D%27ALLEE%27%20and%20libvoie%20like%20%22*cerisier*%22&limit=20&refine=lib_com%3A%22TRELAZE%22
# https://data.angers.fr/api/explore/v2.1/catalog/datasets/calendrier-tri-et-plus/records?select=date_collecte&where=id_secteur%3D%2220160304152520700993%22&limit=20

import json
import urllib.parse
from datetime import date, datetime, timedelta
from enum import Enum

import requests
from waste_collection_schedule import Collection
from waste_collection_schedule.exceptions import SourceArgumentException

TITLE = "Angers Loire Métropole"
DESCRIPTION = "Source script for data.angers.fr"
URL = "https://data.angers.fr/"
TEST_CASES = {}

ICON_MAP = {
    "omr": "mdi:trash-can",
    "emb": "mdi:recycle",
    "enc": "mdi:truck-remove",
    "dv": "mdi:leaf",
    "verre": "mdi:bottle-wine",
}

LABEL_MAP = {
    "OM": "Ordures ménagères",
    "TRI": "Tri sélectif",
}

PARAM_DESCRIPTIONS = {
    # "fr": {
    #     "address": "Votre adresse complète",
    #     "city": "Votre ville"
    # },
    "en": {"address": "Your full address", "city": "Your city"},
    "de": {"address": "Ihre vollständige Adresse", "city": "Ihre Stadt"},
    "it": {"address": "Il tuo indirizzo completo", "city": "La tua città"},
}

PARAM_TRANSLATIONS = {
    # "fr": {
    #     "address": "Adresse",
    #     "city": "Ville"
    # },
    "en": {"address": "Address", "city": "City"},
    "de": {"address": "Adresse", "city": "Stadt"},
    "it": {"address": "Indirizzo", "city": "Città"},
}

EXTRA_INFO = []


class DayNames(Enum):
    MONDAY = "LUNDI"
    TUESDAY = "MARDI"
    WEDNESDAY = "MERCREDI"
    THURSDAY = "JEUDI"
    FRIDAY = "VENDREDI"
    SATURDAY = "SAMEDI"
    SUNDAY = "DIMANCHE"


DAY_NAME_MAP = {
    DayNames.MONDAY: 0,
    DayNames.TUESDAY: 1,
    DayNames.WEDNESDAY: 2,
    DayNames.THURSDAY: 3,
    DayNames.FRIDAY: 4,
    DayNames.SATURDAY: 5,
    DayNames.SUNDAY: 6,
}


class Source:
    api_url_waste_calendar = "https://data.angers.fr/api/explore/v2.1/catalog/datasets/calendrier-tri-et-plus/records?select=date_collecte&where=id_secteur%3D%22{idsecteur}%22&limit=20"
    api_secteur = "https://data.angers.fr/api/explore/v2.1/catalog/datasets/secteurs-de-collecte-tri-et-plus/records?select=id_secteur,cat_secteur&where=typvoie%3D%27{typevoie}%27%20and%20libvoie%20like%20%22*{address}*%22&limit=20&refine=lib_com%3A%22{city}%22"

    def __init__(self, address: str, city: str, typevoie: str) -> None:
        self.address = address
        self.city = city
        self.typevoie = typevoie

    @staticmethod
    def _get_next_weekday(source_date: date, target_day_name: DayNames) -> date:
        # Get the current weekday number
        source_date_weekday = source_date.weekday()

        # Get the target weekday number
        target_weekday = DAY_NAME_MAP[target_day_name]

        # Calculate the number of days until the next target weekday
        days_until_target = (target_weekday - source_date_weekday + 7) % 7
        if days_until_target == 0:  # It is source_date!
            return source_date

        # Calculate the date of the next target weekday
        next_target_date = source_date + timedelta(days=days_until_target)

        return next_target_date

    def _get_idsecteur_address(self, address: str, city: str, typevoie: str) -> dict:
        url = self.api_secteur.format(
            city=urllib.parse.quote(self.city.upper()),
            address=urllib.parse.quote(self.address),
            typevoie=urllib.parse.quote(self.typevoie.upper()),
        )

        response = requests.get(url)

        if response.status_code != 200:
            raise SourceArgumentException("address", "Error response from geocoder")

        data = response.json()["results"]
        if not data:
            raise SourceArgumentException(
                "address", "No results found for the given address and INSEE code"
            )

        return data

    def fetch(self) -> list[Collection]:
        try:
            id_secteurs = self._get_idsecteur_address(
                self.address, self.city, self.typevoie
            )
        except requests.RequestException as e:
            raise SourceArgumentException(
                "address", f"Error fetching address data: {e}"
            )

        entries = []
        for id_secteur in id_secteurs:
            try:
                if id_secteur["cat_secteur"] == "OM":
                    url = self.api_url_waste_calendar.format(
                        idsecteur=urllib.parse.quote(id_secteur["id_secteur"])
                    )
                    data_om = requests.get(url)
                    data_om.raise_for_status()
                    dates_om = [
                        entry["date_collecte"] for entry in data_om.json()["results"]
                    ]
                    entries.append({"type": "OM", "results": dates_om})

                elif id_secteur["cat_secteur"] == "TRI":
                    url = self.api_url_waste_calendar.format(
                        idsecteur=urllib.parse.quote(id_secteur["id_secteur"])
                    )
                    data_tri = requests.get(url)
                    data_tri.raise_for_status()
                    dates_tri = [
                        entry["date_collecte"] for entry in data_tri.json()["results"]
                    ]
                    entries.append({"type": "TRI", "results": dates_tri})
                else:
                    raise SourceArgumentException("city", "Error response from API")
            except requests.RequestException as e:
                raise SourceArgumentException(
                    "city", f"Error fetching collection data: {e}"
                )

        filtered_responses: dict[str, list[str]] = {}
        for response_item in entries:
            waste_collection_per_type = filtered_responses.setdefault(
                response_item["type"], []
            )
            for jour_col in response_item["results"]:
                waste_collection_per_type.append(jour_col)

        final_entries = []
        for _collection_type, _dates in filtered_responses.items():
            for _day in _dates:
                source_date = datetime.today().date()
                for _ in range(4):  # Let's generate a month of schedule
                    next_date = self._get_next_weekday(source_date, DayNames(_day))
                    final_entries.append(
                        Collection(
                            date=next_date,  # Next collection date
                            t=LABEL_MAP.get(
                                _collection_type, _collection_type
                            ),  # Collection type
                            # Collection icon
                            icon=ICON_MAP.get(_collection_type),
                        )
                    )
                    source_date = next_date + timedelta(days=1)

        return final_entries
