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

# Archivos para almacenar la memoria de grupos y automensajes
GROUPS_FILE = 'groups.json'
AUTOMENS_FILE = 'automensajes.json'

# Diccionarios para almacenar dinámicamente la información:
# group_mapping: clave = nombre del grupo (minúsculas), valor = entity
group_mapping = {}
# automensajes: lista de configuraciones. Cada elemento es un diccionario con:
#   "source_name": nombre del grupo fuente (en minúsculas)
#   "source_id": id del grupo fuente (privado)
#   "dest": id del chat destino donde se reenviarán los mensajes
#   "last_message_id": id del último mensaje reenviado (para evitar duplicados)
#   "last_forwarded_time": timestamp del último reenvío (para permitir 1 por hora)
automensajes = []

# Diccionario para llevar registro del último saludo enviado a cada usuario (clave: sender_id, valor: fecha)
last_greetings = {}

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

async def load_automensajes():
    """Carga la configuración de automensajes desde el archivo JSON."""
    global automensajes
    if os.path.exists(AUTOMENS_FILE):
        try:
            with open(AUTOMENS_FILE, 'r') as f:
                automensajes = json.load(f)
        except Exception as e:
            print(f"Error al leer el archivo {AUTOMENS_FILE}: {e}")

def save_automensajes():
    """Guarda la configuración de automensajes en un archivo JSON."""
    try:
        with open(AUTOMENS_FILE, 'w') as f:
            json.dump(automensajes, f)
    except Exception as e:
        print(f"Error al guardar en {AUTOMENS_FILE}: {e}")

def get_peru_time():
    """Obtiene la hora actual en Perú (UTC-5, sin considerar DST)."""
    return datetime.utcnow() - timedelta(hours=5)

async def automensaje_forwarder():
    """
    Tarea en segundo plano que revisa cada minuto:
      - Si la hora (según Perú) está entre 5:01am y 11:59pm,
      - Y ha pasado al menos 1 hora desde el último reenvío de cada automensaje,
        obtiene el último mensaje del grupo fuente y, si es nuevo,
        lo reenvía al chat destino configurado.
    """
    while True:
        now = get_peru_time()
        # Horario permitido: de 5:01 a 23:59
        if (now.hour > 5) or (now.hour == 5 and now.minute >= 1):
            current_timestamp = time.time()
            for config in automensajes:
                if current_timestamp - config.get("last_forwarded_time", 0) >= 3600:
                    try:
                        source_entity = await client.get_entity(config["source_id"])
                        messages = await client.get_messages(source_entity, limit=1)
                        if messages:
                            latest_msg = messages[0]
                            if config.get("last_message_id") != latest_msg.id:
                                dest_chat_id = config["dest"]
                                if latest_msg.media:
                                    await client.send_file(
                                        dest_chat_id,
                                        file=latest_msg.media,
                                        caption=latest_msg.text if latest_msg.text else ""
                                    )
                                else:
                                    await client.send_message(dest_chat_id, latest_msg.text)
                                config["last_message_id"] = latest_msg.id
                                config["last_forwarded_time"] = current_timestamp
                                save_automensajes()
                                print(f"Reenviado mensaje del grupo '{config['source_name']}' al chat {dest_chat_id}.")
                    except Exception as e:
                        print(f"Error en automensaje para '{config.get('source_name', 'desconocido')}': {e}")
        await asyncio.sleep(60)  # Revisa cada minuto

async def start_bot():
    await client.start(phone=PHONE_NUMBER)
    me = await client.get_me()
    print(f"Bot iniciado como {me.first_name} (ID: {me.id})")
    
    # Cargar grupos y automensajes almacenados
    await load_groups()
    await load_automensajes()

    # Iniciar la tarea en segundo plano para automensajes
    asyncio.create_task(automensaje_forwarder())

    # ------------------ Comandos de grupos (funcionalidad existente) ------------------

    @client.on(events.NewMessage(pattern=r'^/addgrupo (\w+)$'))
    async def add_group_handler(event):
        if event.sender_id != me.id:
            print(f"")
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
            print(f"")
            return

        group_name = event.pattern_match.group(1).lower()
        if group_name not in group_mapping:
            await event.reply(f"")
            return

        del group_mapping[group_name]
        save_groups()
        await event.reply(f"Grupo '{group_name}' eliminado.")
        print(f"Grupo '{group_name}' eliminado de la memoria.")

    @client.on(events.NewMessage(pattern=r'^/(vergrupos|listagrupos)$'))
    async def list_groups_handler(event):
        if event.sender_id != me.id:
            print(f"")
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
        if command in ['addgrupo', 'borrargrupo', 'vergrupos', 'listagrupos', 
                       'automensaje', 'verautomensajes', 'listautomensajes', 'borrarautomensaje']:
            return

        if command not in group_mapping:
            await event.reply(f"")
            return

        target_entity = group_mapping[command]
        messages = []
        async for message in client.iter_messages(target_entity, limit=100):
            if message.text or message.media:
                messages.append(message)
        messages.reverse()

        if not messages:
            await event.reply(f"No se encontró información en el grupo '{command}'.")
            return

        for msg in messages:
            try:
                if msg.media:
                    await client.send_file(
                        event.chat_id,
                        file=msg.media,
                        caption=msg.text if msg.text else ""
                    )
                else:
                    await client.send_message(event.chat_id, msg.text)
            except Exception as e:
                print(f"Error al enviar mensaje: {e}")

    # ------------------ Nuevos comandos de automensaje ------------------

    @client.on(events.NewMessage(pattern=r'^/automensaje (\w+)$'))
    async def automensaje_handler(event):
        if event.sender_id != me.id:
            print(f"Comando /automensaje ignorado de usuario: {event.sender_id}")
            return

        source_name = event.pattern_match.group(1).lower()
        print(f"Intentando configurar automensaje para el grupo fuente: {source_name}")

        source_entity = None
        async for dialog in client.iter_dialogs():
            if dialog.is_group and dialog.name.lower() == source_name:
                source_entity = dialog.entity
                break

        if source_entity is None:
            await event.reply(f"Grupo fuente '{source_name}' no encontrado.")
            return

        # Verificar si ya existe una configuración para este grupo fuente en este chat
        for config in automensajes:
            if config["source_id"] == source_entity.id and config["dest"] == event.chat_id:
                await event.reply("Ya existe un automensaje configurado para este grupo en este chat.")
                return

        automensajes.append({
            "source_name": source_name,
            "source_id": source_entity.id,
            "dest": event.chat_id,
            "last_message_id": None,
            "last_forwarded_time": 0
        })
        save_automensajes()
        await event.reply(f"Automensaje configurado: se reenviarán mensajes del grupo privado '{source_name}' a este chat en horario permitido.")
        print(f"Automensaje configurado para '{source_name}' con destino {event.chat_id}.")

    @client.on(events.NewMessage(pattern=r'^/(verautomensajes|listautomensajes)$'))
    async def list_automensajes_handler(event):
        if event.sender_id != me.id:
            print(f"Comando de listado de automensajes ignorado de usuario: {event.sender_id}")
            return

        if not automensajes:
            await event.reply("No hay automensajes configurados.")
            return

        msg_lines = []
        for config in automensajes:
            msg_lines.append(f"Fuente: {config['source_name']} (ID: {config['source_id']}) -> Destino: {config['dest']}")
        await event.reply("Automensajes configurados:\n" + "\n".join(msg_lines))
        print("Automensajes listados.")

    @client.on(events.NewMessage(pattern=r'^/borrarautomensaje (\w+)$'))
    async def delete_automensaje_handler(event):
        if event.sender_id != me.id:
            print(f"")
            return

        source_name = event.pattern_match.group(1).lower()
        # Buscar y eliminar las configuraciones para este grupo fuente en este chat
        to_delete = [config for config in automensajes if config["source_name"] == source_name and config["dest"] == event.chat_id]
        if not to_delete:
            await event.reply(f"No existe automensaje configurado para el grupo fuente '{source_name}' en este chat.")
            return

        for config in to_delete:
            automensajes.remove(config)
        save_automensajes()
        await event.reply(f"Automensaje para el grupo fuente '{source_name}' eliminado de este chat.")
        print(f"Automensaje para '{source_name}' eliminado en el chat {event.chat_id}.")

    # ------------------ Responder a respuestas enviando mensaje privado (una vez al día por usuario) ------------------
    @client.on(events.NewMessage)
    async def reply_greeting_handler(event):
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
                    greeting = "¡Hola! ¿Estás interesado en comprar?"
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
