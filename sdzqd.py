import discord
from discord.ext import commands

# ... ta configuration du bot ...

@bot.event
async def on_ready():
    print(f'Connecté en tant que {bot.user}!')
    
    # C'est ici qu'il faut le mettre :
    try:
        await bot.user.edit(username="PPCF BOT")
        print("Nom du bot changé avec succès en 'PPCF BOT'")
    except discord.HTTPException as e:
        print(f"Impossible de changer le nom (Trop de tentatives ?): {e}")

# ... le reste de ton code ...