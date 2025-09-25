import pandas as pd
from enum import Enum
from collections import namedtuple

Message = namedtuple(
    "Message", "type_message aircraft_index DepartureAirfield_time route"
)
Route = namedtuple("Route", "")


class Feilds(Enum):
    field_3 = "Тип сообщения"


def remove_special_char(string: str):
    if pd.isna(string):
        return string
    else:
        string = (
            string.replace(" \n", "")
            if string.find(" \n") != -1
            else string.replace("\n", "")
        )
        return string[1:-1]


def parse_route(route: str) -> list:
    if route.startswith("M"):
        route = route.split("/")
        print(f"{route=}")
        return route

    if route.startswith("S"):
        route = route.split("/")
        print(f"{route=}")
        return route


sheets = ["Москва"]

df = pd.read_excel("dataset/2024.xlsx", sheet_name="Москва", skiprows=1)
print(f"{repr(df['Сообщение SHR'][0])=}")
shr_message = df["Сообщение SHR"].map(remove_special_char)
first_message = shr_message[0]
arr_split = first_message.split()
print(arr_split)
message = Message(*arr_split[0].split("-"))

if message.route.startswith("M"):
    print(message.route.split("/"))
if message.route.startswith("S"):
    print(message.route.split("/"))

if message.DepartureAirfield_time[:4] == "ZZZZ":
    print(first_message)
    print("find /DEP")
else:
    print(message.DepartureAirfield_time[:4])

print(first_message.find("/ZONA"))
