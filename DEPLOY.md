# 🌐 Permanent Link গাইড (Render ফ্রি হোস্টিং)

লক্ষ্য: `https://blackforge-XXXX.onrender.com` — এমন একটা **পার্মানেন্ট লিংক**,
যেটা যেকোনো জায়গা থেকে ব্রাউজারে খুলবে। খরচ: **০ টাকা**।

> ⏰ ফ্রি প্ল্যানের নিয়ম: ১৫ মিনিট কেউ না ঢুকলে সার্ভার ঘুমিয়ে পড়ে (sleep)।
> লিংক কিন্তু **একই থাকে** — কেউ ঢুকলে ~৩০-৫০ সেকেন্ডে জেগে ওঠে (cold start)।
> সবসময় জাগিয়ে রাখতে চাইলে পেইড প্ল্যান লাগে (~$7/মাস, সম্ভবত)।

---

## ধাপ ১ — GitHub-এ ফাইল তোলা (৫ মিনিট, git ছাড়াই)

1. [github.com](https://github.com)-এ ফ্রি অ্যাকাউন্ট খুলুন (না থাকলে)
2. **New repository** → নাম দিন `blackforge-bot` → **Public** → Create
3. **uploading an existing file**-এ ক্লিক করুন
4. আপনার PC-তে `blackforge-bot.zip` খুলে (extract) **ভেতরের সব ফাইল/ফোল্ডার**
   (`backend/`, `frontend/`, `requirements.txt`, `render.yaml`, `Dockerfile`...)
   টেনে ব্রাউজারে ছাড়ুন (drag-drop)
5. নিচে **Commit changes** চাপুন ✅

## ধাপ ২ — Render-এ চালু করা (৫ মিনিট)

1. [render.com](https://render.com)-এ **GitHub দিয়ে Sign Up** করুন
2. Dashboard → **New +** → **Blueprint** → `blackforge-bot` রিপো সিলেক্ট
   (Blueprint না পেলে: **New +** → **Web Service** → রিপো সিলেক্ট করে
   Build Command: `pip install -r requirements.txt`,
   Start Command: `python backend/app.py` দিন)
3. প্ল্যান **Free** রেখে **Apply/Deploy** চাপুন
4. ২-৪ মিনিটে build শেষ হলে উপরে পাবেন: 🎉
   **`https://blackforge-xxxx.onrender.com`** — এটাই আপনার পার্মানেন্ট লিংক!

## ধাপ ৩ — যাচাই

1. লিংক খুলুন → কালো ড্যাশবোর্ড + SYSTEM READY?
2. `test-emails.txt`-এর ৭টা ইমেইল পেস্ট করে START (SMTP টিক **ছাড়া**)
3. ফলাফল: 2 LIKELY... সরি — **4 LIKELY + 3 INVALID** আসার কথা
   (আগের মেসেজের টেস্ট-১ টেবিল দেখুন)

---

## ⚠️ ক্লাউডের ৩টা সৎ সীমা

| সীমা | ব্যাখ্যা |
|---|---|
| 😴 ঘুম + জাগতে দেরি | ফ্রি প্ল্যানের নিয়ম; লিংক একই থাকে |
| 🗑️ হিস্ট্রি মুছে যায় | ফ্রি ডিস্ক অস্থায়ী (ephemeral) — restart/redeploy-এ পুরনো job মুছে যায়; নতুন job চালানো যায় সবসময় |
| 📡 SMTP সম্ভবত বন্ধ | বেশিরভাগ ক্লাউডে port 25 ব্লক (অনুমানভিত্তিক) — তাই ক্লাউডে **LIVE প্রায় আসবে না**; MX-ভিত্তিক LIKELY/INVALID ঠিকমতো কাজ করবে |

> 💡 **ফুল পাওয়ার (SMTP LIVE চেক) চাইলে:** নিজের PC-তে `run.ps1` চালান —
> ওখানে কোনো ব্লক নেই। ক্লাউড-লিংক = শেয়ার/ডেমো/MX-চেকের জন্য সেরা।

## 🔄 আপডেট করবেন কীভাবে?

PC-তে ফাইল বদলে GitHub-এর একই রিপোতে আবার upload করুন →
Render **অটো-ডিপ্লয়** করে দেবে (১-২ মিনিট), লিংক বদলাবে না।
