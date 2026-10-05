/* Records a reference sample; microphone access begins only on a user click. */
class VoiceboxRecorder {
  constructor(onChange) { this.onChange = onChange; this.file = null; this.url = ''; this.isRecording = false; this.pending = false; this.stream = null; this.recorder = null; this.timer = null; this.startedAt = 0; this.disposed = false; }
  update(message) { this.onChange({ recording: this.isRecording, pending: this.pending, file: this.file, url: this.url, message }); }
  release() { clearInterval(this.timer); this.timer = null; this.stream?.getTracks().forEach(track => track.stop()); this.stream = null; }
  clear() { if (this.isRecording || this.pending) return; if (this.url) URL.revokeObjectURL(this.url); this.url = ''; this.file = null; this.update('Запиши 5–25 секунд без музыки.'); }
  async start() {
    if (this.isRecording || this.pending) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Этот клиент Telegram не поддерживает микрофон. Обнови Telegram или загрузи аудиофайл.');
    this.pending = true; this.update('Разреши доступ к микрофону…');
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
      if (this.disposed) { this.release(); return; }
      const type = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(t => MediaRecorder.isTypeSupported(t));
      this.recorder = type ? new MediaRecorder(this.stream, { mimeType: type }) : new MediaRecorder(this.stream);
      const recorder = this.recorder, chunks = [];
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        const elapsed = (Date.now() - this.startedAt) / 1000;
        this.isRecording = false; this.release();
        if (this.disposed) return;
        const blob = new Blob(chunks, { type: recorder.mimeType || type || 'audio/webm' });
        if (elapsed < 2 || !blob.size) { this.update('Запись слишком короткая. Запиши хотя бы 3 секунды.'); return; }
        if (this.url) URL.revokeObjectURL(this.url);
        const ext = blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : 'webm';
        this.file = new File([blob], `voice-sample.${ext}`, { type: blob.type }); this.url = URL.createObjectURL(blob);
        this.update('Запись готова. Прослушай её, впиши произнесённые слова и нажми «Сохранить голос».');
      };
      recorder.onerror = () => { this.isRecording = false; this.release(); this.update('Ошибка микрофона. Попробуй снова или загрузи файл.'); };
      // Keep the previous recording until permission and recorder setup succeed.
      if (this.url) URL.revokeObjectURL(this.url); this.file = null; this.url = '';
      recorder.start(250); this.startedAt = Date.now(); this.isRecording = true; this.pending = false;
      this.timer = setInterval(() => { const seconds = Math.floor((Date.now() - this.startedAt) / 1000); this.update(`● Запись: ${seconds} / 28 сек. Говори спокойно и чётко.`); if (seconds >= 28) this.stop(); }, 250);
      this.update('● Запись: 0 / 28 сек. Говори спокойно и чётко.');
    } catch (error) {
      this.release(); this.isRecording = false;
      const messages = { NotAllowedError: 'Разреши микрофон в настройках Telegram и устройства, затем попробуй снова.', NotFoundError: 'Микрофон не найден.', NotReadableError: 'Микрофон занят другим приложением.' };
      throw new Error(messages[error.name] || 'Не удалось начать запись. Попробуй снова или загрузи аудиофайл.');
    } finally { this.pending = false; if (!this.isRecording && !this.disposed) this.update(this.file ? 'Предыдущая запись сохранена.' : 'Микрофон выключен.'); }
  }
  stop() { if (this.recorder?.state === 'recording') { clearInterval(this.timer); this.recorder.stop(); this.release(); } }
  dispose() { this.disposed = true; this.stop(); this.release(); if (this.url) URL.revokeObjectURL(this.url); this.url = ''; this.file = null; }
}
window.VoiceboxRecorder = VoiceboxRecorder;
