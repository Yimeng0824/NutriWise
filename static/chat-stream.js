/* POST SSE with chunk-safe UTF-8 decoding and final formatted answer replacement. */
window.askNutritionStream = async function (url, question, onToken, onDone, signal) {
  const response = await fetch(url, {
    method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
    body: JSON.stringify({question}), signal
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `请求失败（${response.status}）`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', complete = false;
  function dispatch(frame) {
    const lines = frame.split('\n');
    const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!data) return; // connection and heartbeat comments
    const value = JSON.parse(data);
    if (event === 'token') onToken(value.text);
    else if (event === 'done') { complete = true; onDone(value.answer); }
    else if (event === 'error') throw new Error(value.error || '回答暂时中断，请重试');
  }
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream: true});
      buffer = buffer.replace(/\r\n/g, '\n');
      let end;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        dispatch(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
      }
      if (done) break;
    }
    if (!complete) throw new Error('连接中断，回答尚未完成，请重试');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
};
