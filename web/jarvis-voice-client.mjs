/**
 * Browser-side playback adapter for a trusted Jarvis application backend.
 * The backend authenticates the user, then forwards text to the private VLAN
 * voice service with a server-only bearer token. Never embed that token here.
 */
export async function speakJarvis(text, {
  endpoint = "/api/jarvis/speak",
  provider = "kokoro",
  voice = "bm_george",
  speed = 0.94,
  signal,
  csrfToken,
} = {}) {
  if (!text || typeof text !== "string") throw new Error("Jarvis needs text to speak");
  const response = await fetch(endpoint, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
    body: JSON.stringify({text, provider, voice, speed}),
    signal,
  });
  if (!response.ok) throw new Error(`Jarvis voice returned HTTP ${response.status}`);
  if (!(response.headers.get("Content-Type") || "").includes("audio/wav")) {
    throw new Error("Jarvis voice response was not audio");
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

export async function playJarvis(text, options = {}) {
  const url = await speakJarvis(text, options);
  const audio = new Audio(url);
  try {
    await audio.play();
    await new Promise((resolve, reject) => {
      audio.onended = resolve;
      audio.onerror = () => reject(new Error("Jarvis playback failed"));
    });
  } finally {
    audio.pause();
    URL.revokeObjectURL(url);
  }
}
