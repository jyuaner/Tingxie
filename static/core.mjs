export function validateAudio(file) {
  if (!file || file.size === 0) return "音频文件是空的，请重新选择或录音。";
  if (file.size > 200 * 1024 * 1024) return "文件超过 200 MB，请先将录音分段。";
  if (!/\.(wav|mp3|m4a|mp4|flac|ogg|webm|aac|wma|opus)$/i.test(file.name)) {
    return "暂不支持该格式，请选择 WAV、MP3、M4A、FLAC 等音频文件。";
  }
  return "";
}

export function formatTime(seconds = 0) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const parts = [Math.floor(total / 60) % 60, total % 60];
  if (total >= 3600) parts.unshift(Math.floor(total / 3600));
  return parts.map((part) => String(part).padStart(2, "0")).join(":");
}

export function characterCount(text) {
  return [...text.replace(/\s/g, "")].length;
}
