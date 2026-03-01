import discord
import re
import datetime
import database
from discord.ext import commands, tasks

# --- HELPER FONCTIONS ---
async def update_discord_role(guild, member, new_rank_name):
    """Met à jour les rôles Discord d'un membre en fonction de son grade"""
    try:
        # 1. Liste des tous les rôles de grades possibles (T-1 à T-8)
        all_ranks = [database.get_rank_name(i) for i in range(1, 9)]
        
        # 2. Identifier les rôles à retirer (tous les grades sauf le nouveau)
        to_remove = [r for r in member.roles if r.name in all_ranks and r.name != new_rank_name]
        if to_remove:
            await member.remove_roles(*to_remove, reason="Mise à jour Grade Bot")
        
        # 3. Ajouter le nouveau rôle s'il ne l'a pas déjà
        new_role = discord.utils.get(guild.roles, name=new_rank_name)
        if new_role:
            if new_role not in member.roles:
                await member.add_roles(new_role, reason="Mise à jour Grade Bot")
        else:
            print(f"⚠️ Rôle introuvable sur le serveur : {new_rank_name}")
            
    except Exception as e:
        print(f"❌ Erreur update_discord_role pour {member}: {e}")

# Classe de Vue pour le bouton Cohost
class CohostView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) 

    @discord.ui.button(label="Devenir Cohost", style=discord.ButtonStyle.primary, custom_id="claim_cohost")
    async def claim_cohost(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_stats = database.get_user_stats(str(interaction.user))
        if not user_stats:
            await interaction.response.send_message("❌ Tu n'es pas enregistré dans la base de données (/register) !", ephemeral=True)
            return

        try:
            rank_num = user_stats[2]
        except IndexError:
             await interaction.response.send_message("❌ Erreur de lecture de ton profil.", ephemeral=True)
             return

        if rank_num < 5:
            rank_name = database.get_rank_name(rank_num)
            await interaction.response.send_message(f"❌ Grade insuffisant. Tu es **{rank_name}**, il faut être au moins **T-5 Sous-lieutenant**.", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        found = False
        for index, field in enumerate(embed.fields):
            if "Cohost" in field.name:
                embed.set_field_at(index, name="🥈 Cohost", value=interaction.user.mention, inline=True)
                found = True
                break

        if not found:
            embed.add_field(name="🥈 Cohost", value=interaction.user.mention, inline=True)

        await interaction.response.edit_message(embed=embed, view=None)
        await interaction.followup.send(f"✅ {interaction.user.mention} est maintenant le Cohost de cette session !", ephemeral=False)

# Tâche planifiée pour le Salaire
@tasks.loop(hours=12) 
async def check_salary(bot: commands.Bot):
    await bot.wait_until_ready()
    now = datetime.datetime.now()   
    
    if now.day == 1:
        month_key = f"{now.month:02d}-{now.year}"
        
        if not database.is_month_paid(month_key):
            print(f"💰 Paiement des salaires pour {month_key} en cours...")
            
            channel = None
            for guild in bot.guilds:
                channel = discord.utils.get(guild.text_channels, name="💵salaire")
                if channel: break
            
            if not channel:
                print("⚠️ Salon #salaire introuvable !")
                return

            embed = discord.Embed(title=f"📅 Salaires du Mois ({month_key})", description="Distribution automatique des Robux.", color=discord.Color.gold())
            lines = []
            members = database.get_all_members_with_ranks()

            for username, rank in members:
                amount = 0
                rank_name = database.get_rank_name(rank)

                if rank == 6: amount = 5
                elif rank >= 7: amount = 10
                
                if amount > 0:
                    try:
                        new_pending = database.add_pending_robux(username, amount)
                        member_obj = None
                        for guild in bot.guilds:
                            member_obj = guild.get_member_named(username)
                            if member_obj: break
                        
                        display_name = member_obj.mention if member_obj else username
                        lines.append(f"• {display_name} ({rank_name}) : **+{amount} R$** (Total: {new_pending} R$)")
                    except Exception as e:
                        print(f"Erreur salaire {username}: {e}")

            if not lines: lines.append("Aucun membre éligible.")
            embed.add_field(name="💸 Bénéficiaires", value="\n".join(lines), inline=False)
            embed.set_footer(text="Réclamez vos Robux avec un admin !")
            await channel.send(embed=embed)
            database.mark_month_paid(month_key)
            print("✅ Salaires payés !")

def setup(bot):

    if not check_salary.is_running():
        check_salary.start(bot)

    @bot.event
    async def on_member_join(member):
        try:
            database.add_user(str(member))
            print(f"✅ {member} rejoint.")
        except Exception:
            pass

    @bot.tree.command(name='hello')
    async def hello(interaction: discord.Interaction):
        await interaction.response.send_message(f'Bonjour {interaction.user.mention}! 👋')

    @bot.tree.command(name='ping')
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message(f'Pong! {round(bot.latency * 1000)}ms')

    # ---------------------------------------------------------
    # COMMANDE LOG (Restreinte à #event-logs)
    # ---------------------------------------------------------
    @bot.tree.command(name='log', description='Valider le déploiement actif et donner les points')
    async def log(
        interaction: discord.Interaction,
        membres: str,
        cohost: discord.Member = None,
        mvp: discord.Member = None,
        notes: str = None
    ):
        # Restriction Salon : doit contenir "📝event-logs"
        if "📝event-logs" not in interaction.channel.name.lower():
             await interaction.response.send_message("❌ Commande interdite ici ! Utilise le salon **#📝event-logs**.", ephemeral=True)
             return

        await interaction.response.defer()

        host_name = str(interaction.user)
        log_num = database.get_active_deployment(host_name)

        if not log_num:
             await interaction.followup.send("❌ Tu n'as pas de déploiement en cours !", ephemeral=True)
             return

        mentions = re.findall(r'<@!?(\d+)>', membres)
        participants = []
        promotions = [] 
        exclude_ids = [interaction.user.id]
        if cohost: exclude_ids.append(cohost.id)

        # Host (+2)
        database.add_user(host_name)
        database.add_points(host_name, 2)
        participants.append(f"👑 Host: {interaction.user.mention} (+2 pts)")
        
        # Cohost (+2)
        if cohost:
            database.add_user(str(cohost))
            database.add_points(str(cohost), 2)
            participants.append(f"🥈 Cohost: {cohost.mention} (+2 pts)")

        # Participants (+1)
        if mentions:
            participants.append("\n**Participants (+1 pt):**")
            for user_id in mentions:
                if int(user_id) in exclude_ids: continue 

                try:
                    member = interaction.guild.get_member(int(user_id)) or await bot.fetch_user(int(user_id))
                    username = member.name
                    database.add_user(username)
                    
                    old_stats = database.get_user_stats(username)
                    old_rank_name = database.get_rank_name(old_stats[2]) 

                    stats = database.add_points(username, 1)
                    new_rank_name = stats[2]
                    
                    participants.append(f"• {member.mention} ({new_rank_name})")

                    if old_rank_name != new_rank_name:
                        promotions.append(f"• {member.mention} : {old_rank_name} ➔ {new_rank_name}")
                        # Mise à jour rôle Discord
                        if isinstance(member, discord.Member):
                            await update_discord_role(interaction.guild, member, new_rank_name)

                except Exception as e:
                    print(f"Erreur log user {user_id}: {e}")

        mvp_text = ""
        if mvp:
            database.add_user(mvp.name)
            database.add_points(mvp.name, 1)
            mvp_text = f"\n🌟 **MVP :** {mvp.mention} (+1 point)"

        embed = discord.Embed(title=f"📋 Log de Déploiement #{log_num}", description=f"Validé par {interaction.user.mention}", color=discord.Color.green())
        embed.add_field(name="👥 Récompenses", value="\n".join(participants), inline=False)
        if promotions: embed.add_field(name="🎉 Promotions", value="\n".join(promotions), inline=False)
        if mvp_text: embed.add_field(name="Bonus", value=mvp_text, inline=False)
        if notes: embed.add_field(name="📝 Notes", value=notes, inline=False)
        embed.set_footer(text=f"ID: {interaction.user.id}")

        database.end_deployment(host_name)
        await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------
    # COMMANDES ADMIN (Points & Robux)
    # ---------------------------------------------------------
    @bot.tree.command(name='admin_points', description="[Admin] Gérer les points et grades de plusieurs membres")
    @discord.app_commands.checks.has_permissions(administrator=True)
    @discord.app_commands.describe(action="Ajouter ou Retirer", amount="Quantité", membres="Mentions (@user @user...)")
    @discord.app_commands.choices(action=[
        discord.app_commands.Choice(name="Ajouter", value="add"),
        discord.app_commands.Choice(name="Retirer", value="remove")
    ])
    async def admin_points(interaction: discord.Interaction, action: str, amount: int, membres: str):
        await interaction.response.defer()
        
        mentions = re.findall(r'<@!?(\d+)>', membres)
        if not mentions:
            await interaction.followup.send("❌ Aucun membre mentionné.", ephemeral=True)
            return

        real_amount = amount if action == "add" else -amount
        logs = []

        for user_id in mentions:
            try:
                member = interaction.guild.get_member(int(user_id)) or await bot.fetch_user(int(user_id))
                username = member.name
                database.add_user(username)

                old_stats = database.get_user_stats(username)
                old_rank_name = database.get_rank_name(old_stats[2])

                # Ajout/Retrait points (gère automatiquement le grade dans la DB)
                stats = database.add_points(username, real_amount)
                new_points, new_rank_num, new_rank_name = stats
                
                log_line = f"• {member.mention} : {old_stats[1]}➔{new_points} pts"
                
                # Vérification changement de grade
                if old_rank_name != new_rank_name:
                    log_line += f" | **{new_rank_name}**"
                    # Mise à jour rôle Discord
                    if isinstance(member, discord.Member):
                        await update_discord_role(interaction.guild, member, new_rank_name)
                
                logs.append(log_line)

            except Exception as e:
                logs.append(f"• Erreur ID {user_id}: {e}")

        embed = discord.Embed(
            title=f"🔧 Admin Points ({action.upper()})",
            description=f"Action: {real_amount} points par personne.",
            color=discord.Color.red()
        )
        embed.add_field(name="Résultats", value="\n".join(logs), inline=False)
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name='admin_robux', description="[Admin] Gérer les Robux en attente")
    @discord.app_commands.checks.has_permissions(administrator=True)
    @discord.app_commands.describe(action="Ajouter ou Retirer", amount="Quantité", membres="Mentions (@user @user...)")
    @discord.app_commands.choices(action=[
        discord.app_commands.Choice(name="Ajouter", value="add"),
        discord.app_commands.Choice(name="Retirer", value="remove")
    ])
    async def admin_robux(interaction: discord.Interaction, action: str, amount: int, membres: str):
        await interaction.response.defer()
        
        mentions = re.findall(r'<@!?(\d+)>', membres)
        if not mentions:
            await interaction.followup.send("❌ Aucun membre mentionné.", ephemeral=True)
            return

        real_amount = amount if action == "add" else -amount
        logs = []

        for user_id in mentions:
            try:
                member = interaction.guild.get_member(int(user_id)) or await bot.fetch_user(int(user_id))
                username = member.name
                
                # On utilise add_pending_robux qui gère l'addition
                new_pending = database.add_pending_robux(username, real_amount)
                
                # On s'assure que ça ne descend pas sous 0 (Optionnel, mais propre)
                if new_pending < 0:
                    # Correction si négatif
                    database.add_pending_robux(username, -new_pending) # Remet à 0
                    new_pending = 0
                
                logs.append(f"• {member.mention} : Solde attente = **{new_pending} R$**")

            except Exception as e:
                logs.append(f"• Erreur ID {user_id}: {e}")

        embed = discord.Embed(
            title=f"🔧 Admin Robux ({action.upper()})",
            description=f"Action: {real_amount} R$ par personne.",
            color=discord.Color.red()
        )
        embed.add_field(name="Résultats", value="\n".join(logs), inline=False)
        await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------
    # COMMANDE PROMOTE (le conseil des 4)
    # ---------------------------------------------------------
    @bot.tree.command(name='promote', description="Promouvoir un T-6 Lieutenant en T-7 Capitaine")
    async def promote(interaction: discord.Interaction, membre: discord.Member):
        # ... (Vérifications droits & existence membre) ...

        # Récupérer stats actuelles
        user_stats = database.get_user_stats(membre.name)
        current_rank = user_stats[2]
        current_points = user_stats[1]
        
        # Vérifier éligibilité : Doit être T-6 et avoir 30+ points
        if current_rank != 6:
            await interaction.response.send_message(f"❌ {membre.mention} n'est pas T-6 Lieutenant.", ephemeral=True)
            return

        if current_points < 30:
            await interaction.response.send_message(f"❌ Points insuffisants ({current_points}/30).", ephemeral=True)
            return

        # Appliquer la promotion forcée
        try:
            # Cette fonction doit simplement faire un UPDATE rank = 7 sans condition de points
            new_rank_name = database.force_rank_update(membre.name, 7)
            await update_discord_role(interaction.guild, membre, new_rank_name)
            
            embed = discord.Embed(
                title="🎖️ Promotion Spéciale",
                description=f"Félicitations ! {membre.mention} a été promu **{new_rank_name}** par le Conseil.",
                color=discord.Color.gold()
            )
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur lors de la promotion : {e}", ephemeral=True)

    @bot.tree.command(name='profile', description="Voir le profil d'un membre")
    async def profile(interaction: discord.Interaction, membre: discord.Member = None):
        user = membre or interaction.user
        data = database.get_user_stats(str(user))
        if not data:
            if user.id == interaction.user.id:
                database.add_user(str(user))
                data = database.get_user_stats(str(user))
            else:
                await interaction.response.send_message(f"❌ {user.mention} n'a pas de profil.", ephemeral=True)
                return
        
        try: username, points, rank_num, notes, total, eligible, nb_msg, nb_cmd, attente = data
        except ValueError: username, points, rank_num, notes, total, eligible, nb_msg, nb_cmd = data[:8]; attente = 0

        rank_name = database.get_rank_name(rank_num)
        next_rank_num = rank_num + 1
        next_rank_points = database.get_next_rank_points(points)
        progression = f"Vers **{database.get_rank_name(next_rank_num)}** ({points}/{next_rank_points}pts)" if next_rank_num <= 8 else f"✨ Grade Maximum Atteint ! ({points}/{next_rank_points}pts)"

        embed = discord.Embed(title=f"📂 Dossier : {username}", color=discord.Color.blue())
        embed.add_field(name="🎖️ Grade", value=rank_name, inline=True)
        embed.add_field(name="💰 En attente", value=f"{attente} R$", inline=True)
        embed.add_field(name="📈 Progression", value=progression, inline=False)
        if notes: embed.add_field(name="📝 Notes", value=notes, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name='nigger')
    async def nigger(interaction: discord.Interaction):
        await interaction.response.send_message(f' {interaction.user.mention} a dit NIGGEEEEEEEEEEEEERRRRRRRRRR')

    @bot.tree.command(name='claim', description="[Admin] Réclamer les robux")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def claim(interaction: discord.Interaction, membre: discord.User):
        success, montant = database.claim_robux(str(membre))
        if not success:
            await interaction.response.send_message(f"❌ {membre.mention} n'a rien à réclamer.", ephemeral=True)
            return
        embed = discord.Embed(title="💰 Robux Réclamés", description=f"{membre.mention} a reçu **{montant} robux** !", color=discord.Color.green())
        embed.set_footer(text=f"Validé par {interaction.user}", icon_url=interaction.user.avatar.url)
        await interaction.response.send_message(embed=embed)

    # ---------------------------------------------------------
    # COMMANDE DEPLOIEMENT (Restreinte à #déploiement)
    # ---------------------------------------------------------
    @bot.tree.command(name='déploiement', description="Annoncer et démarrer un déploiement (Grade T-6+)")
    async def déploiement(
        interaction: discord.Interaction,
        host: discord.Member,
        jeu: str,
        date: str,
        cohost: discord.Member = None,
        notes: str = None
    ):
        # Restriction Salon : doit contenir "🐴déploiment"
        if "🐴déploiment" not in interaction.channel.name.lower():
             await interaction.response.send_message("❌ Commande interdite ici ! Utilise le salon **#🐴déploiment**.", ephemeral=True)
             return

        user_stats = database.get_user_stats(str(interaction.user))
        if not user_stats:
             database.add_user(str(interaction.user))
             user_stats = database.get_user_stats(str(interaction.user))
        
        rank_num = user_stats[2]
        if rank_num < 6:
             rank_name = database.get_rank_name(rank_num)
             await interaction.response.send_message(f"❌ Grade insuffisant ({rank_name}). Min: **T-6 Lieutenant**.", ephemeral=True)
             return

        existing_log = database.get_active_deployment(str(interaction.user))
        if existing_log:
             await interaction.response.send_message(f"❌ Déploiement n°{existing_log} déjà en cours ! Finis-le avec `/log`.", ephemeral=True)
             return

        log_num = database.increment_log_count()
        database.start_deployment(str(interaction.user), log_num)

        view = CohostView() if not cohost else None
        cohost_val = cohost.mention if cohost else "(libre)"

        embed = discord.Embed(title=f"Déploiment n°{log_num}", description=f"Un nouveau Déploiment est prévu sur : {jeu}", color=discord.Color.orange())
        embed.add_field(name="👑 Host", value=host.mention, inline=True)
        embed.add_field(name="🥈 Cohost", value=cohost_val, inline=True)
        embed.add_field(name="🎮 Jeu", value=jeu, inline=False)
        embed.add_field(name="📅 Date & Heure", value=date, inline=False)
        if notes: embed.add_field(name="📝 Notes", value=notes, inline=False)
        
        await interaction.response.send_message(content=f"<@&{1317093605986537492}>", embed=embed, view=view)
        message = await interaction.original_response()
        try:
            await message.add_reaction("✅")
            await message.add_reaction("🟧")
            await message.add_reaction("❌")
        except: pass
    
    @bot.tree.command(name='cancel', description="Annuler un déploiement en cours (Host uniquement)")
    async def cancel(interaction: discord.Interaction, raison: str):
        host_name = str(interaction.user)
        log_id = database.get_active_deployment(host_name)

        if not log_id:
            await interaction.response.send_message("❌ Tu n'as aucun déploiement actif à annuler.", ephemeral=True)
            return

        database.end_deployment(host_name)
        
        embed = discord.Embed(title=f"❌ Déploiement #{log_id} Annulé", description=f"Le déploiement a été annulé.", color=discord.Color.dark_grey())
        embed.add_field(name="Raison", value=raison, inline=False)
        embed.set_footer(text=f"Annulé par {host_name}")
        
        await interaction.response.send_message(embed=embed)