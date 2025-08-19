from ..util import discord, human_money

def run(broker, settings):
    # buy dollars -> shares
    px = broker.price(settings.symbol)
    shares = round(settings.weekly_dca / px, 4)
    if shares < 0.01:
        discord("DCA skipped: amount too small for a share fraction.")
        return
    res = broker.buy_equity(settings.symbol, shares, tag="DCA", note=f"${settings.weekly_dca} weekly DCA")
    discord(f"🧊 DCA: bought {shares} {settings.symbol} @ ~{human_money(px)}")
