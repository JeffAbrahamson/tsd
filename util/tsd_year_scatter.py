#!/usr/bin/env python3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import argparse


def load_data(file_path):
    """Load data from the given file path."""
    return pd.read_csv(
        file_path,
        delimiter="\t",
        header=None,
        names=["Date", "Stimulus"],
        parse_dates=["Date"],
    )


def create_stimulus_matrix(data):
    """Create a matrix indicating the presence of stimulus for each day of each year."""
    start_year = data["Date"].dt.year.min()
    end_year = data["Date"].dt.year.max()
    stimulus_matrix = pd.DataFrame(
        index=pd.RangeIndex(start=start_year, stop=end_year + 1),
        columns=pd.RangeIndex(start=1, stop=367),
    )  # 366 days + 1 for indexing ease

    for year in stimulus_matrix.index:
        yearly_data = data[
            (data["Date"] >= str(year)) & (data["Date"] < str(year + 1))
        ]
        for _, row in yearly_data.iterrows():
            day_of_year = row["Date"].dayofyear
            stimulus_matrix.at[year, day_of_year] = row["Stimulus"]

    return stimulus_matrix.fillna(0)


def plot_stimulus_matrix(stimulus_matrix):
    """Plot the stimulus matrix using scatter plot for large round dots."""
    plt.figure(figsize=(20, 10))

    # Plot each point as a large dot
    for year in stimulus_matrix.index:
        for day in stimulus_matrix.columns:
            if stimulus_matrix.at[year, day] == 1:
                plt.scatter(
                    day, year - stimulus_matrix.index[0], color="green", s=10
                )  # s is the size of the dot

    plt.title("Stimulus Presence by Month and Year")
    plt.xlabel("Month")
    plt.ylabel("Year")

    # Setting x-axis labels to months and x-axis limits
    month_ticks = [
        15,
        46,
        74,
        105,
        135,
        166,
        196,
        227,
        258,
        288,
        319,
        349,
    ]  # Approximate middle of each month
    month_labels = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    plt.xticks(ticks=month_ticks, labels=month_labels)
    plt.xlim(1, 366)  # Setting x-axis to span the full year

    plt.yticks(
        ticks=np.arange(len(stimulus_matrix)), labels=stimulus_matrix.index
    )
    plt.show()


def main(file_path):
    data = load_data(file_path)
    stimulus_matrix = create_stimulus_matrix(data)
    plot_stimulus_matrix(stimulus_matrix)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Visualize stimulus presence by month and year with large dots."
    )
    parser.add_argument(
        "-f", "--file", required=True, help="Path to the data file."
    )
    args = parser.parse_args()

    main(args.file)
