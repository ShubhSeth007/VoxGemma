from flask import Flask, request, jsonify
import importlib
import threading
import time
import sys

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

agent_module = None


def get_agent():
    global agent_module
    if agent_module is None:
        try:
            agent_module = importlib.import_module("agent")
        except Exception as exc:
            raise RuntimeError(f"Unable to import agent.py: {exc}")
    return agent_module


@app.route('/api/command', methods=['POST'])
def api_command():
    payload = request.get_json(silent=True) or {}
    command = payload.get('command', '').strip()
    if not command:
        return jsonify({'success': False, 'error': 'Missing command.'}), 400

    try:
        result = process_command(command)
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500
    return jsonify(result)


@app.route('/api/status', methods=['GET'])
def api_status():
    a = get_agent()
    return jsonify({
        'last_spoken': a.session.get('last_spoken', ''),
        'tts_lang': a.session.get('tts_lang', 'en'),
        'session_log': a.session.get('session_log', [])[-10:],
    })


def process_command(command):
    a = get_agent()
    command_en = a.normalize_command(command)
    parsed = a.parse_intent_with_gemma(command_en)
    action = parsed.get('action', 'unknown')
    params = {k: v for k, v in parsed.items() if k != 'action'}
    a.emit_event('intent', action=action, params=params, method='terminal')
    t_start = time.time()

    result_text = ''
    success = True

    try:
        if action == 'open_app':
            raw_name = parsed.get('app_name', '')
            resolved = a.resolve_app_name(raw_name)
            a.subprocess.Popen(resolved, shell=True)
            result_text = f'Opened {raw_name or resolved}.'
            a.log_event(command, action, result_text)

        elif action == 'new_tab':
            a.pyautogui.hotkey('ctrl', 't')
            time.sleep(1)
            result_text = 'Opened new tab.'
            a.log_event(command, action, result_text)

        elif action == 'address_bar':
            a.pyautogui.hotkey('ctrl', 'l')
            time.sleep(0.3)
            result_text = 'Address bar focused.'
            a.log_event(command, action, result_text)

        elif action == 'navigate':
            url = parsed.get('url', '')
            if url:
                a.navigate_to_url(url)
                time.sleep(2)
                desc = a.describe_screen()
                result_text = f'Navigated to {url}. {desc}'
                a.log_event(command, action, url)
            else:
                result_text = 'Could not parse the website address.'
                success = False

        elif action == 'click_element':
            target = parsed.get('target', '')
            if target:
                clicked = a.smart_click(target)
                result_text = f'Clicked {target}.' if clicked else f'Unable to click {target}.'
                success = clicked
                a.log_event(command, action, result_text)
            else:
                result_text = 'No click target found in the command.'
                success = False

        elif action == 'describe_current':
            result_text = a.describe_screen()
            a.log_event(command, action, result_text)

        elif action == 'read_content':
            result_text = a.read_screen_content()
            a.log_event(command, action, result_text)

        elif action == 'get_tabs':
            result_text = a.get_browser_tabs()
            a.log_event(command, action, result_text)

        elif action == 'read_emails':
            result_text = a.read_emails()
            a.log_event(command, action, result_text)

        elif action == 'urgent_emails':
            result_text = a.check_urgent_emails()
            a.log_event(command, action, result_text)

        elif action == 'summarize_session':
            result_text = a.summarize_my_session()
            a.log_event(command, action, result_text)

        elif action == 'set_language':
            lang_name = parsed.get('language', 'english').lower()
            lang_code = a.LANGUAGE_MAP.get(lang_name, 'en')
            a.session['tts_lang'] = lang_code
            result_text = f'Language switched to {lang_name}.'
            a.emit_event('language', lang=lang_code)
            a.log_event(command, action, lang_name)

        elif action == 'chat':
            result_text = a.call_ollama_chat(command_en)
            a.log_event(command, action, result_text)

        else:
            _, b64 = a.capture_screen(max_size=1920)
            result_text = a.call_ollama(
                f"You are a voice assistant for a completely blind user. "
                f"They said: \"{command}\" "
                "If this is about the screen, look at the screenshot and answer fully. "
                "If this is a general question, answer it clearly. "
                "Respond in natural spoken sentences, 2-3 sentences max. "
                "Never say you cannot see the screen.",
                b64_image=b64,
                temperature=0.3,
            )
            if not result_text:
                result_text = 'I am not sure about that. Could you rephrase?'
            a.log_event(command, 'chat', result_text)

    except Exception as exc:
        result_text = f'Error while processing command: {exc}'
        success = False

    a.emit_event('responding', text=result_text, lang=a.session['tts_lang'], action=action, ms=int((time.time() - t_start) * 1000))
    return {
        'success': success,
        'action': action,
        'parsed': parsed,
        'result': result_text,
    }


def clear_screen():
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.flush()


def draw_box(title, lines):
    width = max(len(title), *(len(line) for line in lines)) + 4
    print('+' + '-' * width + '+')
    print(f'| {title.ljust(width - 2)} |')
    print('+' + '-' * width + '+')
    for line in lines:
        print(f'| {line.ljust(width - 2)} |')
    print('+' + '-' * width + '+')


def draw_ui(last_command, last_action, last_result, last_error, last_log):
    clear_screen()
    print('==============================================')
    print(' VoxGemma Terminal Dashboard (Flask backend)')
    print('==============================================')
    print()

    if last_error:
        draw_box('ERROR', [last_error])
    else:
        draw_box('LAST COMMAND', [last_command or '<none>'])
        draw_box('LAST ACTION', [last_action or '<none>'])
        result_lines = last_result.split('\n') if last_result else ['<no result yet>']
        draw_box('LAST RESULT', result_lines[:8])

    print()
    print('Menu:')
    print(' 1) Describe screen')
    print(' 2) Read screen content')
    print(' 3) Get browser tabs')
    print(' 4) Read emails')
    print(' 5) Check urgent emails')
    print(' 6) Session summary')
    print(' 7) Enter custom command')
    print(' 8) Show last 10 logs')
    print(' q) Quit')
    print()
    if last_log:
        print('Recent activity:')
        for entry in last_log[-6:]:
            print(f" - {entry}")
        print()


def format_log_entry(entry):
    time_str = entry.get('time', '?')
    command = entry.get('command', '')
    action = entry.get('action', '')
    result = entry.get('result', '')
    return f"[{time_str}] {action} - {command} -> {result}"


def run_terminal_ui():
    last_command = ''
    last_action = ''
    last_result = ''
    last_error = ''
    last_log = []

    while True:
        draw_ui(last_command, last_action, last_result, last_error, last_log)
        choice = input('Select an option: ').strip().lower()

        if choice in ('q', 'quit', 'exit'):
            break

        if choice == '1':
            command = 'describe the screen'
        elif choice == '2':
            command = 'read the content'
        elif choice == '3':
            command = 'list browser tabs'
        elif choice == '4':
            command = 'read my emails'
        elif choice == '5':
            command = 'is there anything urgent in my inbox'
        elif choice == '6':
            command = 'what did I do today'
        elif choice == '7':
            command = input('Enter command: ').strip()
            if not command:
                last_error = 'No command entered.'
                continue
        elif choice == '8':
            last_error = ''
            continue
        else:
            last_error = 'Invalid menu option.'
            continue

        last_error = ''
        last_command = command

        try:
            result = process_command(command)
            last_action = result.get('action', '')
            last_result = result.get('result', '')
            a = get_agent()
            last_log = [format_log_entry(e) for e in a.session.get('session_log', [])[-10:]]
        except Exception as exc:
            last_error = str(exc)
            last_result = ''
            last_action = ''

    print('\nShutting down. Goodbye!')


def run_flask():
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)


def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print('Starting Flask API backend at http://127.0.0.1:5000')
    print('Press Enter to continue to terminal dashboard...')
    input()
    run_terminal_ui()


if __name__ == '__main__':
    main()
