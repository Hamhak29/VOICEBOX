const tg = window.Telegram?.WebApp;
const $ = (id) => document.getElementById(id);
let voices = [], polling = false;
function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); }
async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(typeof error.detail === 'string' ? error.detail : `Ошибка ${response.status}`); }
  return response.json();
}
const post = (path, data) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
async function action(button, fn) { button.disabled = true; try { await fn(); } catch (e) { notice(e.message, true); } finally { button.disabled = false; } }
function card(title, body) { const el = document.createElement('div'); el.className = 'card'; const heading = document.createElement('h3'); heading.textContent = title; el.append(heading); if (body) { const p = document.createElement('p'); p.textContent = body; el.append(p); } return el; }
function audioCard(item) {
  const el = card(item.profile_name || 'Озвучка', item.text);
  if (item.status === 'completed') {
    const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'none'; audio.src = `/audio/${encodeURIComponent(item.id)}`; el.append(audio);
    const link = document.createElement('a'); link.className = 'download'; link.textContent = 'Скачать WAV'; link.href = audio.src; link.download = 'voicebox.wav'; el.append(link);
    const send = document.createElement('button'); send.textContent = 'Отправить мне в Telegram'; send.onclick = () => action(send, async () => { await post(`/telegram/send/${encodeURIComponent(item.id)}`, {}); notice('Аудио отправлено в чат с ботом.'); }); el.append(send);
  } else { const status = document.createElement('p'); status.textContent = item.status === 'failed' ? `Ошибка: ${item.error || 'Не удалось создать озвучку'}` : 'Обрабатываем…'; el.append(status); }
  return el;
}
async function loadVoices() {
  voices = await api('/profiles'); $('voice').replaceChildren(); $('voice-list').replaceChildren();
  for (const v of voices) { const opt = document.createElement('option'); opt.value = v.id; opt.textContent = v.name; $('voice').append(opt); $('voice-list').append(card(v.name, v.voice_type === 'preset' ? 'Готовый голос' : `Образцов: ${v.sample_count}`)); }
  if (!voices.length) { const opt = document.createElement('option'); opt.textContent = 'Добавь голос в разделе «Голоса»'; opt.value = ''; $('voice').append(opt); }
}
async function loadHistory() { const data = await api('/history?limit=30'); $('history-list').replaceChildren(...data.items.map(audioCard)); if (!data.items.length) $('history-list').append(card('Пока пусто', 'Здесь появятся твои озвучки.')); }
async function ensureModel(engine) {
  const name = engine === 'qwen' ? 'qwen-tts-0.6B' : 'qwen-custom-voice-0.6B';
  const status = await api('/models/status');
  const model = status.models.find((m) => m.model_name === name);
  if (model?.downloaded) return;
  notice('Загружаем голосовую модель. Это нужно только при первом использовании.');
  await post('/models/download', { model_name: name });
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) { await new Promise((r) => setTimeout(r, 4000)); const update = await api('/models/status'); if (update.models.find((m) => m.model_name === name)?.downloaded) return; }
  throw new Error('Загрузка ещё не завершена. Повтори чуть позже.');
}
async function monitor(id) {
  polling = true;
  try { while (polling) { const item = await api(`/history/${encodeURIComponent(id)}`); $('result').replaceChildren(audioCard(item)); if (['completed','failed'].includes(item.status)) { notice(item.status === 'completed' ? 'Готово. Можно прослушать и отправить запись.' : item.error || 'Генерация не удалась.', item.status === 'failed'); break; } await new Promise((r) => setTimeout(r, 3000)); } } finally { polling = false; }
}
$('generate').onclick = () => action($('generate'), async () => {
  const voice = voices.find((v) => v.id === $('voice').value); const text = $('text').value.trim();
  if (!voice || !text) throw new Error('Выбери голос и введи текст.');
  if (voice.voice_type !== 'preset' && !voice.sample_count) throw new Error('Для этого голоса нужно загрузить образец.');
  const engine = voice.voice_type === 'preset' ? 'qwen_custom_voice' : 'qwen';
  await ensureModel(engine); notice('Создаём озвучку. Можно дождаться здесь или вернуться к истории позже.');
  const item = await post('/generate', { profile_id: voice.id, text, language: $('language').value, engine, model_size: '0.6B', max_chunk_chars: 300 });
  tg?.HapticFeedback?.notificationOccurred('success'); await monitor(item.id);
});
$('add-preset').onclick = () => action($('add-preset'), async () => { const name = $('preset').value; await post('/profiles', { name, language: 'ru', voice_type: 'preset', preset_engine: 'qwen_custom_voice', preset_voice_id: name, default_engine: 'qwen_custom_voice' }); await loadVoices(); notice('Голос добавлен. Открой «Озвучка».'); });
$('add-clone').onclick = () => action($('add-clone'), async () => {
  const file = $('sample').files[0], reference = $('reference').value.trim(), name = $('clone-name').value.trim();
  if (!file || !reference || !name) throw new Error('Укажи название, аудио и точную расшифровку.');
  if (file.size > 20 * 1024 * 1024) throw new Error('Образец должен быть меньше 20 МБ.');
  const draftKey = `voicebox-clone-draft:${name}`;
  let id = sessionStorage.getItem(draftKey);
  if (!id) { const profile = await post('/profiles', { name, language: 'ru', voice_type: 'cloned', default_engine: 'qwen' }); id = profile.id; sessionStorage.setItem(draftKey, id); }
  const form = new FormData(); form.append('file', file); form.append('reference_text', reference);
  await api(`/profiles/${encodeURIComponent(id)}/samples`, { method: 'POST', body: form }); sessionStorage.removeItem(draftKey); await loadVoices(); notice('Образец сохранён. Голос готов к озвучке.');
});
$('refresh').onclick = () => action($('refresh'), loadHistory);
$('text').oninput = () => { $('count').textContent = `${$('text').value.length} / 2000`; };
document.querySelectorAll('[data-tab]').forEach((button) => { button.onclick = async () => { document.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b === button)); ['create','voices','history'].forEach((id) => { $(id).hidden = id !== button.dataset.tab; }); if (button.dataset.tab === 'history') { try { await loadHistory(); } catch (e) { notice(e.message, true); } } }; });
async function start() {
  tg?.ready(); tg?.expand();
  function theme() { const p = tg?.themeParams; if (!p) return; const map = { bg:'bg_color', card:'secondary_bg_color', text:'text_color', hint:'hint_color', accent:'button_color' }; for (const [key, value] of Object.entries(map)) if (p[value]) document.documentElement.style.setProperty(`--${key}`, p[value]); }
  theme(); tg?.onEvent('themeChanged', theme);
  const config = await api('/telegram/config');
  if (!config.configured) { notice('Студия подготовлена. Осталось подключить Telegram-бота.'); return; }
  if (!tg?.initData) { notice('Открой VOICEBOX кнопкой в Telegram-боте.', true); return; }
  await post('/telegram/session', { init_data: tg.initData }); await loadVoices(); $('studio').hidden = false; notice('Личная студия подключена.');
}
start().catch((e) => notice(e.message, true));
