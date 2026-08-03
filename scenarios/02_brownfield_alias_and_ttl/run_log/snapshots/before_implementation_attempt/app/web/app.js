const shortenForm = document.getElementById("shorten-form");
const resultBox = document.getElementById("result");
const errorBox = document.getElementById("error");
const shortLink = document.getElementById("short-link");

function extractErrorMessage(data) {
  if (!data) return "Request failed";
  if (data.error && data.error.message) return data.error.message;
  if (data.detail) return data.detail;
  return "Request failed";
}

shortenForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorBox.classList.add("hidden");
  resultBox.classList.add("hidden");

  const long_url = document.getElementById("long_url").value;
  const custom_alias = document.getElementById("custom_alias").value || undefined;
  const ttlRaw = document.getElementById("ttl_seconds").value;
  const ttl_seconds = ttlRaw ? Number(ttlRaw) : undefined;

  try {
    const res = await fetch("/api/shorten", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ long_url, custom_alias, ttl_seconds }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(extractErrorMessage(data));
    shortLink.href = data.short_url;
    shortLink.textContent = data.short_url;
    resultBox.classList.remove("hidden");
  } catch (err) {
    errorBox.textContent = err.message;
    errorBox.classList.remove("hidden");
  }
});

const copyBtn = document.getElementById("copy-btn");
if (copyBtn) {
  copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(shortLink.href);
  });
}

const analyticsForm = document.getElementById("analytics-form");
const analyticsResult = document.getElementById("analytics-result");

analyticsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = document.getElementById("code").value;
  try {
    const res = await fetch(`/api/analytics/${code}`);
    const data = await res.json();
    if (!res.ok) throw new Error(extractErrorMessage(data));
    analyticsResult.textContent = JSON.stringify(data, null, 2);
    analyticsResult.classList.remove("hidden");
  } catch (err) {
    analyticsResult.textContent = err.message;
    analyticsResult.classList.remove("hidden");
  }
});
