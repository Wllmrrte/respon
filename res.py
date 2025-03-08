import asyncio
import logging
import time
import json
import os
from datetime import datetime, timedelta
from telethon import TelegramClient, events

# Credenciales (datos sensibles: protege esta información)
API_ID = 9161657
API_HASH = '400dafb52292ea01a8cf1e5c1756a96a'
PHONE_NUMBER = '+51981119038'

# Archivo para almacenar la memoria de grupos (para la funcionalidad existente)
GROUPS_FILE = 'groups.json'

# Diccionario para almacenar la información de grupos agregados (funcionalidad existente)
group_mapping = {}

# Diccionario para almacenar el último saludo enviado a cada usuario (funcionalidad existente)
last_greetings = {}

# Nuevo diccionario para almacenar los automensajes activos.
# Clave: ID del grupo; Valor: dict con alias, spam_msg y task (objeto de asyncio.Task)
auto_messages = {}

# Crear el cliente de Telegram (la sesión se guarda en "session.session")
client = TelegramClient('session', API_ID, API_HASH)

async def load_groups():
    """Carga la información de los grupos desde el archivo JSON."""
    global group_mapping
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, 'r') as f:
                data = json.load(f)
            # Recuperar el entity de cada grupo usando su ID
            for group_name, group_id in data.items():
                try:
                    entity = await client.get_entity(group_id)
                    group_mapping[group_name] = entity
                except Exception as e:
                    print(f"Error al cargar el grupo '{group_name}': {e}")
        except Exception as e:
            print(f"Error al leer el archivo {GROUPS_FILE}: {e}")

def save_groups():
    """Guarda la información de los grupos en un archivo JSON (almacenando solo el ID)."""
    data = {name: entity.id for name, entity in group_mapping.items()}
    try:
        with open(GROUPS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error al guardar en {GROUPS_FILE}: {e}")

def get_peru_time():
    """Obtiene la hora actual en Perú (UTC-5, sin considerar DST)."""
    return datetime.utcnow() - timedelta(hours=5)

async def auto_message_loop(chat_id, spam_msg):
    """Bucle infinito que envía el mensaje spam cada 35 minutos, 
    evitando hacerlo entre 1:00am y 5:30am hora Perú."""
    while True:
        peru_time = get_peru_time()
        # Si la hora actual está entre 1:00 y 5:30, se espera hasta las 5:30
        if peru_time.hour >= 1 and (peru_time.hour < 5 or (peru_time.hour == 5 and peru_time.minute < 30)):
            now = peru_time
            allowed_time = now.replace(hour=5, minute=30, second=0, microsecond=0)
            # Si ya pasó las 5:30, ajustar al día siguiente (aunque en esta condición no ocurrirá)
            if now >= allowed_time:
                allowed_time += timedelta(days=1)
            seconds_to_wait = (allowed_time - now).total_seconds()
            await asyncio.sleep(seconds_to_wait)
            continue
        try:
            await client.send_message(chat_id, spam_msg)
        except Exception as e:
            print(f"Error al enviar automensaje en {chat_id}: {e}")
        await asyncio.sleep(40 * 60)  # espera 40 minutos

async def cleanup_tasks():
    """Tarea que limpia periódicamente los automensajes que se hayan cancelado o finalizado."""
    while True:
        await asyncio.sleep(600)  # cada 10 minutos
        to_remove = []
        for group_id, info in auto_messages.items():
            task = info.get('task')
            if task is None or task.done():
                to_remove.append(group_id)
        for group_id in to_remove:
            del auto_messages[group_id]
            print(f"")

async def start_bot():
    await client.start(phone=PHONE_NUMBER)
    me = await client.get_me()
    print(f"Bot iniciado como {me.first_name} (ID: {me.id})")
    
    # Cargar grupos almacenados (funcionalidad existente)
    await load_groups()

    # Iniciar tarea de autolimpiado de automensajes
    asyncio.create_task(cleanup_tasks())

    # ------------------ Comandos de grupos (funcionalidad existente) ------------------

    @client.on(events.NewMessage(pattern=r'^/addgrupo (\w+)$'))
    async def add_group_handler(event):
        if event.sender_id != me.id:
            return

        group_name = event.pattern_match.group(1).lower()
        print(f"Intentando agregar grupo: {group_name}")

        target_entity = None
        async for dialog in client.iter_dialogs():
            if dialog.is_group and dialog.name.lower() == group_name:
                target_entity = dialog.entity
                break

        if target_entity is None:
            await event.reply(f"Grupo '{group_name}' no encontrado.")
            return

        group_mapping[group_name] = target_entity
        save_groups()
        await event.reply(f"Grupo '{group_name}' agregado. Ahora puedes usar /{group_name} para acceder a su información.")
        print(f"Grupo '{group_name}' agregado a la memoria.")

    @client.on(events.NewMessage(pattern=r'^/borrargrupo (\w+)$'))
    async def delete_group_handler(event):
        if event.sender_id != me.id:
            return

        group_name = event.pattern_match.group(1).lower()
        if group_name not in group_mapping:
            await event.reply(f"Grupo '{group_name}' no existe.")
            return

        del group_mapping[group_name]
        save_groups()
        await event.reply(f"Grupo '{group_name}' eliminado.")
        print(f"Grupo '{group_name}' eliminado de la memoria.")

    @client.on(events.NewMessage(pattern=r'^/(vergrupos|listagrupos)$'))
    async def list_groups_handler(event):
        if event.sender_id != me.id:
            return

        if not group_mapping:
            await event.reply("No hay grupos registrados.")
            return

        group_list = ", ".join(sorted(group_mapping.keys()))
        await event.reply(f"Grupos registrados: {group_list}")
        print(f"Grupos listados: {group_list}")

    @client.on(events.NewMessage(pattern=r'^/(\w+)$'))
    async def dynamic_command_handler(event):
        if event.sender_id != me.id:
            return

        command = event.pattern_match.group(1).lower()
        # Excluir comandos reservados
        if command in ['addgrupo', 'borrargrupo', 'vergrupos', 'listagrupos']:
            return

        if command not in group_mapping:
            await event.reply(f"Grupo '{command}' no registrado.")
            return

        target_entity = group_mapping[command]
        messages = await client.get_messages(target_entity, limit=100)
        if not messages:
            await event.reply(f"No se encontró información en el grupo '{command}'.")
            return

        # Revertir el orden para reenviar en orden cronológico
        messages = list(reversed(messages))
        message_ids = [msg.id for msg in messages]
        try:
            # Reenvía los mensajes exactamente como fueron enviados, conservando formato y emojis
            await client.forward_messages(event.chat_id, message_ids, target_entity)
        except Exception as e:
            print(f"Error al reenviar mensajes: {e}")

    # ------------------ Responder a respuestas enviando mensaje privado (funcionalidad existente) ------------------
    @client.on(events.NewMessage)
    async def reply_greeting_handler(event):
        # Procesar solo si el mensaje proviene de un grupo
        if not event.is_group:
            return

        # Si el mensaje es una respuesta y el remitente no es el bot
        if event.is_reply and event.sender_id != me.id:
            try:
                current_date = get_peru_time().date()
                # Verificar si ya se envió un saludo hoy a este usuario
                if event.sender_id in last_greetings and last_greetings[event.sender_id] == current_date:
                    return
                replied_msg = await event.get_reply_message()
                # Comprobar que el mensaje respondido fue enviado por el bot
                if replied_msg.sender_id == me.id:
                    greeting = "¡Hola! ¿Estás interesado en comprar LEDERDATABOT? ☺️"
                    # Enviar el saludo en privado al usuario que respondió
                    if replied_msg.media:
                        await client.send_file(
                            event.sender_id,
                            file=replied_msg.media,
                            caption=greeting
                        )
                    else:
                        await client.send_message(event.sender_id, greeting)
                    # Registrar que ya se envió el saludo hoy
                    last_greetings[event.sender_id] = current_date
            except Exception as e:
                print(f"Error al enviar saludo: {e}")

    # ------------------ Nuevos comandos para Automensajes ------------------
    @client.on(events.NewMessage(pattern=r'^/automensaje (\S+)$'))
    async def add_auto_message_handler(event):
        if event.sender_id != me.id:
            return
        spam_command = event.pattern_match.group(1).strip()
        # Asegurarse de que el comando spam comience con '/'
        if not spam_command.startswith('/'):
            spam_command = '/' + spam_command

        if not event.is_group:
            await event.reply("El comando /automensaje solo puede usarse en grupos.")
            return

        chat = await event.get_chat()
        group_id = chat.id
        # Crear un alias corto a partir del título del grupo (se usa la primera palabra en minúsculas)
        if hasattr(chat, 'title') and chat.title:
            group_alias = chat.title.split()[0].lower()
        else:
            group_alias = str(group_id)

        if group_id in auto_messages:
            await event.reply("Ya hay un automensaje activo en este grupo.")
            return

        task = asyncio.create_task(auto_message_loop(group_id, spam_command))
        auto_messages[group_id] = {
            "alias": group_alias,
            "spam_msg": spam_command,
            "task": task
        }
        await event.reply(f"Automensaje '{spam_command}' agregado para el grupo '{group_alias}' (ID: {group_id}).")
        print(f"Automensaje agregado para el grupo '{group_alias}' (ID: {group_id}) con comando {spam_command}.")

    @client.on(events.NewMessage(pattern=r'^/verautomensajes$'))
    async def view_auto_messages_handler(event):
        if event.sender_id != me.id:
            return
        if not auto_messages:
            await event.reply("No hay automensajes activos.")
            return
        response = "Automensajes activos:\n"
        for group_id, info in auto_messages.items():
            response += f"Grupo: {info['alias']} (ID: {group_id}) -> Mensaje: {info['spam_msg']}\n"
        await event.reply(response)

    @client.on(events.NewMessage(pattern=r'^/borrarautomensaje(?: (\S+))?$'))
    async def delete_auto_message_handler(event):
        if event.sender_id != me.id:
            return
        param = event.pattern_match.group(1)
        # Si se ejecuta en grupo sin parámetro, se elimina el automensaje del grupo actual
        if event.is_group and not param:
            chat = await event.get_chat()
            group_id = chat.id
            if group_id not in auto_messages:
                await event.reply("No hay automensaje activo en este grupo.")
                return
            auto_messages[group_id]['task'].cancel()
            del auto_messages[group_id]
            await event.reply("Automensaje eliminado para este grupo.")
            print(f"Automensaje eliminado para el grupo ID: {group_id}.")
        else:
            # Si se proporciona un parámetro (alias), se busca y elimina
            param = param.strip().lower() if param else None
            found = False
            for group_id, info in list(auto_messages.items()):
                if info['alias'] == param:
                    auto_messages[group_id]['task'].cancel()
                    del auto_messages[group_id]
                    await event.reply(f"Automensaje eliminado para el grupo '{param}'.")
                    print(f"Automensaje eliminado para el grupo '{param}' (ID: {group_id}).")
                    found = True
                    break
            if not found:
                await event.reply(f"No se encontró automensaje para el grupo '{param}'.")

    print("Bot en ejecución. Esperando comandos...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            asyncio.run(start_bot())
        except Exception as e:
            print(f"Error: {e}. Reintentando en 5 segundos...")
            time.sleep(5)

