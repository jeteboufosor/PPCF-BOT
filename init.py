import os
import discord
from discord.ext import commands
from database import init_db

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# CONFIGURATION INTENTS
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True # CORRECTION: Déplacé AVANT la création du bot

class MyBot(commands.Bot):
    async def setup_hook(self):
        # 1. Enregistrer les commandes
        from fonctions import setup as register_commands
        register_commands(self)

        # 2. Initialiser la DB
        init_db()
        print("✅ Base de données initialisée !")

        # 3. Synchronisation
        dev_guild_id = os.getenv("DISCORD_DEV_GUILD")
        if dev_guild_id:
            guild = discord.Object(id=int(dev_guild_id))
            print(f"🔄 Sync Dev Guild ({dev_guild_id})...")
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print("✅ Commandes synchronisées (Instantané) !")
        else:
            # AVERTISSEMENT IMPORTANT
            print("🌍 Sync Global : Cela peut prendre jusqu'à 1 HEURE pour apparaître.")
            await self.tree.sync()
            print("✅ Sync Global envoyé à Discord.")

# Création du bot avec les intents complets
bot = MyBot(command_prefix=commands.when_mentioned, intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f'✅ Connecté en tant que {bot.user} (ID: {bot.user.id})')
    print('------')

def start():
    """Start the Discord bot."""
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise RuntimeError("Le token Discord n'est pas défini.")

    # Nettoyage token
    token = token.strip().replace("'", "").replace('"', "")
    if token.startswith("Bot "):
        token = token.split(" ", 1)[1]

    try:
        bot.run(token)
    except discord.errors.LoginFailure:
        print("❌ Login failed: Token invalide.")
    except Exception as e:
        print(f"❌ Erreur critique : {e}")

if __name__ == '__main__':
    start()
