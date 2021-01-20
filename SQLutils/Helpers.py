import os
import csv
from pathlib import Path

def colsForSql(cols):
    """
    Function that transforms a list of strings containing the name of columns to a string
    ready to use in an SQL query. Ex: ["name","age","gender"]  ==> "name","age","gender"

    :param cols: the list of column names
    :return: a string

    """
    cols = list(map(lambda c: '"'+c+'"', cols))

    return ",".join(cols)


def colsAndTypes(types):
    """
    Function that transform a dictionary with column names (string) as keys and types (string) as values
    to a string to use in an SQL query. Ex: {"name":"text", "Age":"numeric"} ==> '"name" text, "Age" numeric'

    :param types: dictionary
    :return: string
    """
    cols = types.keys()
    query_parts = list(map(lambda c: f"\"{c}\" {types[c]}", cols))

    return ",".join(query_parts)


def writeCsvFile(data, filename, foldername):
    """
    Function that takes a list of python dictionaries and generate a CSV file from them

    :param data: the list of dictionaries
    :param filename: the of the csv file that will be generated
    :generate a csv file

    The generated file will be in the folder missing_data

    """
    try:
        # we check if the folder exists
        if not os.path.exists(foldername):
            # if the folder wasn't created, we create it
            os.makedirs(foldername)
        # we open a new file
        with open(f"./{foldername}/{filename}", 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=data[0].keys())
            # we write the headers of the CSV file
            writer.writeheader()
            # we write all the data
            for item in data:
                writer.writerow(item)
    except IOError:
        print("I/O error")


def save_stats_file(filename, df):
    """
    We save stats csv file in the stats directory

    :param filename: name of the file
    :param df: pandas dataframe with the data
    """
    if not os.path.exists(f"./stats/stats_{filename}"):
        Path(
            f"./stats/stats_{filename}").mkdir(parents=True, exist_ok=True)
    if os.path.isfile(f"./stats/stats_{filename}/stats_{filename}.csv"):
        os.remove(f"./stats/stats_{filename}/stats_{filename}.csv")

    df.to_csv(f"./stats/stats_{filename}/stats_{filename}.csv")


def timeDeltaToMonths(timeDelta):
    """
    Function that transforms from the type TimeDelta to months

    :return: number of month
    """

    return round(timeDelta.total_seconds() / 2592000, 2)


def AbsTimeLapse(df, new_col, first_date, second_date):
    """
    Computes a new column that gives the absolute differences (in months) between two column dates

    :param df: pandas dataframe
    :param new_col: new column name (for the column that will store the results)
    :param first_date: first date column name
    :param second_date: second date column name
    """
    df[new_col] = abs(df[second_date] - df[first_date])
    df[new_col] = df[new_col].apply(timeDeltaToMonths)

def extract_var_id(var_name):
    """
    Function that returns the id of the variable of a given variable

    :param var_name: the variable name
    :return:a string
    """

    return var_name.split()[0]


def check_categorical_var(data):
    """
    Function that gets the data of a variable and return True if this variable is categorical

    :param data:the data of the variable
    :return: Bool
    """
    for item in data:
        if item is not None:
            if isinstance(item, str):
                return True

    if len(data.unique()) > 10:
        return False
    return True


def save_charts_html(folders):
    """
    Function that displays all the charts of the project in one HTML page

    :param folders: the list of the folder names containing the charts we want to display
    :return:a string
    """
    style = """
        <style>
        *{
            padding:0px;
            margin:0px;
            font-family: 'Oswald', sans-serif;
        }
        .title{
            height:11vh;
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:32px;
            font-weight:600;
            background-color:#f5fafd
        }
        .section-title{
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:25px;
            font-weight:600;
            margin-top:50px

        }
        .container{
            display:flex;
            flex-wrap:wrap;
            justify-content:center;
        }
        img{
            margin:10px 5px
        }
        @media only screen and (max-width: 700px) {
            img {
                width:80vw;
                height:80vw;
            }
        }
        </style>
    """
    body = ""
    for folder in folders:
        images = ""
        for img in os.listdir(f"./charts/{folder}"):
            images += f'<img src="./charts/{folder}/{img}"   />'
        body += f'<div class="section-title">{folder}</div><div class="container">{images}</div>'
    text = f'''
    <html>
        <head>
            <link rel="preconnect" href="https://fonts.gstatic.com">
            <link href="https://fonts.googleapis.com/css2?family=Oswald:wght@300&display=swap" rel="stylesheet">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>PETALE Charts</title>
            {style}
        </head>
        <body>
            <div class="title">Petal Charts</div>
            
            {body}
            
        </body>
    </html>
    '''

    file = open("PETALE_Charts.html", "w")
    file.write(text)
    file.close()


def retrieve_categorical(df, ids):
    """
    Function that return a dataframe containing only categorical variables from a given dataframe

    :param df: a pandas dataframe
    :return:a string
    """
    categorical_cols = [
        col for col in df.columns if (check_categorical_var(df[col]))]
    for col_id in ids:
        if col_id not in categorical_cols:
            categorical_cols.append(col_id)
    return df[categorical_cols]


def retrieve_numerical(df, ids):
    """
    Function that return a dataframe containing only numerical variables from a given dataframe

    :param df: a pandas dataframe
    :return:a string
    """
    numerical_cols = [
        col for col in df.columns if (not check_categorical_var(df[col]))]
    for col_id in ids:
        if col_id not in numerical_cols:
            numerical_cols.append(col_id)
    return df[numerical_cols]
