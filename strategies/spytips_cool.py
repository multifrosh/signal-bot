import os
import pandas as pd
import yahooquery as yq
from .constants import *
import numpy as np
import time

def spy_tips_cool():
    for i in range(TRY_COUNT):
        try:
            spy = yq.Ticker('^SP500TR').history(period="max", adj_ohlc=True, adj_timezone=False)
            tips = yq.Ticker('TIP').history(period="max", adj_ohlc=True, adj_timezone=False)
        except Exception as e:
            print(f"({i+1}/{TRY_COUNT}) Failed to download data from Yahoo Finance: {e}")
            time.sleep(2)  # wait before retrying
            continue
        # check if the data is empty
        if spy.empty and tips.empty:
            print(f"({i+1}/{TRY_COUNT}) Failed to download data from Yahoo Finance. Please check your internet connection or the ticker symbols.")
            time.sleep(2)  # wait before retrying
        else:
            break
    else:
        return "Error", "Failed to download data from Yahoo Finance after multiple attempts.", "Please try again later manually"
    
    # Extract date index from MultiIndex and set as DataFrame index
    date_level_str_spy = pd.Index([str(x) for x in spy.index.get_level_values("date")])
    date_level_str_tips = pd.Index([str(x) for x in tips.index.get_level_values("date")])

    # Find which ones have time info
    colon_mask_spy = date_level_str_spy.str.contains(":")
    colon_mask_tips = date_level_str_tips.str.contains(":")

    # Strip time info from affected rows
    spy.index = pd.to_datetime(date_level_str_spy.where(~colon_mask_spy, date_level_str_spy.str.split(" ").str[0]))
    tips.index = pd.to_datetime(date_level_str_tips.where(~colon_mask_tips, date_level_str_tips.str.split(" ").str[0]))

    spy_close = spy['close']
    tips_close = tips['close']
    spy_sma_rolling = spy_close.rolling(window=SPY_SMA).mean()
    tips_sma_rolling = tips_close.rolling(window=TIPS_SMA).mean()
    spy_diff = (spy_close - spy_sma_rolling) / spy_sma_rolling
    tips_diff = (tips_close - tips_sma_rolling) / tips_sma_rolling
    fileName = HISTORY_FILENAME+"_"+ str(SPY_SMA)+"_"+ str(TIPS_SMA)+"_"+str(COOLDOWN_DAYS)+".txt"
    last_entry = None
    if not os.path.exists(fileName):
        # find cooldown days number of in or out market days in a continuous sequence
        consecutive_days = 1
        for i in range(2, min(len(spy_diff), len(tips_diff))):
            if (spy_diff.iloc[-i] > 0 and tips_diff.iloc[-i]) == (spy_diff.iloc[-i+1] > 0 and tips_diff.iloc[-i+1] > 0):
                consecutive_days += 1
            else:
                consecutive_days = 1
            if consecutive_days >= COOLDOWN_DAYS:
                break
        else:
            print("Could not find a continuous sequence of cooldown days.")
            return "Error", "Could not find a continuous sequence of cooldown days.", "This happens if the data is not sufficient or the cooldown days are too high."
        
        # calculate the strategy forward to the end of the data
        f = open(fileName, 'w')
        indicator = None
        cooldown = 0
        for j in range(i, 0, -1):
            if np.isnan(spy_diff.iloc[-j]) or np.isnan(tips_diff.iloc[-j]):
                return "Error", None, "SMA calculation failed, please try again later. Some indicators are NaN."
            if spy_diff.iloc[-j] > 0 and tips_diff.iloc[-j] > 0 and cooldown == 0:
                if indicator == None:
                    cooldown = 0
                elif indicator == SELL:
                    cooldown = COOLDOWN_DAYS
                indicator = BUY
            elif cooldown == 0:
                if indicator == None:
                    cooldown = 0
                elif indicator == BUY:
                    cooldown = COOLDOWN_DAYS
                indicator = SELL
            f.write(f"{spy.index[-j]},{spy_close.iloc[-j]},{tips_close.iloc[-j]},{spy_sma_rolling.iloc[-j]},{tips_sma_rolling.iloc[-j]},{indicator == BUY},{cooldown}\n")
            if cooldown > 0:
                cooldown -= 1
        f.close()
    else:
        f = open(fileName, 'r')
        file_c = f.readlines()
        f.close()
        last_entry = file_c[-1].split(",")
        if last_entry[0] == str(spy.index[-1]):
            print("Already checked today")
            return None, None, None
        # get index of last entry in spy data
        last_date = pd.to_datetime(last_entry[0])
        last_index = spy.index.get_loc(last_date)
        last_rev_index = last_index - len(spy.index)
        cooldown = int(last_entry[6])
        indicator = BUY if last_entry[5] == "True" else SELL

        assert last_rev_index < -1, "Last entry index is not negative, something went wrong with the data."

        # iterate over all new entries
        for j in range(last_rev_index + 1, 0):
            if np.isnan(spy_diff.iloc[j]) or np.isnan(tips_diff.iloc[j]):
                return "Error", None, "SMA calculation failed, please try again later. Some indicators are NaN."
            if cooldown > 0:
                cooldown -= 1
            if spy_diff.iloc[j] > 0 and tips_diff.iloc[j] > 0 and cooldown == 0:
                if indicator == SELL:
                    cooldown = COOLDOWN_DAYS
                indicator = BUY
            elif cooldown == 0:
                if indicator == BUY:
                    cooldown = COOLDOWN_DAYS
                indicator = SELL
            f = open(fileName, 'a')
            f.write(f"{spy.index[j]},{spy_close.iloc[j]},{tips_close.iloc[j]},{spy_sma_rolling.iloc[j]},{tips_sma_rolling.iloc[j]},{indicator == BUY},{cooldown}\n")
            f.close()

        last_indicator = BUY if last_entry[5] == "True" else SELL

    f = open(fileName, 'r')
    file_c = f.readlines()
    f.close()
    new_entry = file_c[-1].split(",")
    new_entry = [new_entry[0]] + [float(x) for x in new_entry[1:5]] + [new_entry[5] == "True", int(new_entry[6])]
    spy_indicator = BUY if new_entry[1] > new_entry[3] else SELL
    tips_indicator = BUY if new_entry[2] > new_entry[4] else SELL
    total_indicator = BUY if spy_indicator == BUY and tips_indicator == BUY else SELL
    if last_entry is None:
        subject = MAIN_SIGNAL_CHANGE_LONG.format(COOLDOWN_DAYS) if new_entry[5] else MAIN_SIGNAL_CHANGE_SHORT.format(COOLDOWN_DAYS)
        subject2 = ""
        text = f"Currently in market ({new_entry[6]} cooldown days remaining)\n" if new_entry[5] else f"Currently in cash ({new_entry[6]} cooldown days remaining)\n"
        text += f"The SIGNAL is {total_indicator}\n"
        text += f"The SPY signal is {spy_indicator}"
        text += f" with a difference of {spy_diff.iloc[-1]:.2%}\n"
        text += f"The TIPS signal is {tips_indicator}"
        text += f" with a difference of {tips_diff.iloc[-1]:.2%}\n"
        return subject, subject2, text
    last_entry = [last_entry[0]] + [float(x) for x in last_entry[1:5]] + [last_entry[5] == "True", int(last_entry[6])]
    subject = ""
    subject2 = ""
    if new_entry[5] and not last_entry[5]:
        subject = MAIN_SIGNAL_CHANGE_LONG.format(COOLDOWN_DAYS)
    elif not new_entry[5] and last_entry[5]:
        subject = MAIN_SIGNAL_CHANGE_SHORT.format(COOLDOWN_DAYS)
    else:
        # get last cooldown warning
        for i in COOLDOWN_WARNINGS:
            if new_entry[6] <= i and last_entry[6] > i:
                subject = COOLDOWN_WARNINGS_TEXT[COOLDOWN_WARNINGS.index(i)]

    if (new_entry[1] > new_entry[3]) != (last_entry[1] > last_entry[3]) or (new_entry[2] > new_entry[4]) != (last_entry[2] > last_entry[4]):
        subject2 = INDICATOR_CHANGE_TITLE

    last_spy_indicator = BUY if last_entry[1] > last_entry[3] else SELL
    last_tips_indicator = BUY if last_entry[2] > last_entry[4] else SELL
    last_indicator = BUY if last_spy_indicator == BUY and last_tips_indicator == BUY else SELL

    text = f"Currently in market ({new_entry[6]} cooldown days remaining)\n" if new_entry[5] else f"Currently in cash ({new_entry[6]} cooldown days remaining)\n"
    text += f"The SIGNAL remains {total_indicator}\n" if total_indicator == last_indicator else f"The SIGNAL has changed to {total_indicator}\n"
    text += f"The SPY signal remains {spy_indicator}" if spy_indicator == last_spy_indicator else f"The SPY signal has changed to {spy_indicator}"
    text += f" with a difference of {spy_diff.iloc[-1]:.2%}\n"
    text += f"The TIPS signal remains {tips_indicator}" if tips_indicator == last_tips_indicator else f"The TIPS signal has changed to {tips_indicator}"
    text += f" with a difference of {tips_diff.iloc[-1]:.2%}\n"

    if DAILY_NOTIFICATION and subject == "" and subject2 == "":
        subject = "Daily Notification"

    return subject, subject2, text