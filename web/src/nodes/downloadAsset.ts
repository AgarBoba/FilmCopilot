const EXTENSIONS: Record<string, string> = {
  'image/png': '.png',
  'image/jpeg': '.jpg',
  'image/webp': '.webp',
  'video/mp4': '.mp4',
  'video/webm': '.webm',
  'video/quicktime': '.mov',
};

/** Characters that are not allowed in file names on macOS / Windows. */
const UNSAFE = /[\\/:*?"<>|\u0000-\u001f]/g;


/** Download a node's asset, named after the node ("胡萝卜尝试.jpg"). */
export async function downloadAsset(url: string, name: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`下载失败（${response.status}）`);
  const blob = await response.blob();
  const extension = EXTENSIONS[blob.type] ?? '';
  const base = name.replace(UNSAFE, ' ').trim() || 'download';
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = base.endsWith(extension) ? base : `${base}${extension}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
