"use client";

import { translations, type Locale } from "./i18n";

export function LandingPage({
  lang,
  onLaunchApp,
  onOpenVerify,
}: {
  lang: Locale;
  onLaunchApp: () => void;
  onOpenVerify: () => void;
}) {
  const t = translations[lang];

  return (
    <div className="space-y-16 pb-12">
      {/* Hero Section */}
      <section className="relative overflow-hidden rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-900/90 via-slate-950 to-slate-950 p-6 md:p-12 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-950/40 px-3.5 py-1 text-xs font-medium text-emerald-300">
          {t.hero.badge}
        </div>

        <h1 className="mt-5 text-4xl font-extrabold tracking-tight sm:text-5xl md:text-6xl">
          {t.hero.title1} <span className="bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 bg-clip-text text-transparent">{t.hero.title2}</span>
        </h1>

        <p className="mx-auto mt-5 max-w-2xl text-base text-slate-300 md:text-lg">
          {t.hero.subtitle}
        </p>

        {/* CTA Buttons */}
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <button
            type="button"
            onClick={onLaunchApp}
            className="rounded-lg bg-emerald-500 px-6 py-3.5 text-base font-bold text-slate-950 shadow-lg shadow-emerald-500/25 transition-all hover:bg-emerald-400 hover:shadow-emerald-500/40"
          >
            {t.hero.ctaPrimary} &rarr;
          </button>
          <a
            href="https://t.me/Es0TrustBot"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-950/40 px-5 py-3.5 text-base font-semibold text-sky-200 transition-colors hover:border-sky-400 hover:bg-sky-900/60"
          >
            <svg className="h-5 w-5 fill-current" viewBox="0 0 24 24">
              <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.562 8.161c-.18.716-.962 4.084-1.362 5.75-.17.705-.436.941-.692.964-.556.051-.979-.368-1.517-.72-.843-.551-1.32-.894-2.138-1.433-.945-.623-.332-.966.207-1.527.14-.147 2.583-2.369 2.63-2.571.006-.025.011-.122-.047-.174-.058-.052-.143-.034-.205-.02-.088.02-1.488.948-4.2 2.781-.397.272-.757.406-1.079.399-.356-.008-1.042-.202-1.552-.367-.625-.203-1.122-.31-1.078-.654.023-.179.271-.363.743-.553 2.91-1.268 4.852-2.105 5.827-2.511 2.773-1.157 3.349-1.358 3.725-1.365.083-.001.267.02.387.118.101.082.129.193.142.271.013.078.029.256.016.395z" />
            </svg>
            {t.hero.ctaTelegram}
          </a>
          <button
            type="button"
            onClick={onOpenVerify}
            className="rounded-lg border border-slate-700 bg-slate-900 px-5 py-3.5 text-base font-medium text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800"
          >
            {t.hero.ctaVerify}
          </button>
        </div>

        {/* Live Metrics Grid */}
        <div className="mt-12 grid grid-cols-2 gap-4 border-t border-slate-800/80 pt-8 sm:grid-cols-4">
          <div>
            <p className="text-2xl font-bold text-emerald-400 md:text-3xl">{t.hero.stat1Value}</p>
            <p className="mt-1 text-xs text-slate-400 md:text-sm">{t.hero.stat1Label}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-emerald-400 md:text-3xl">{t.hero.stat2Value}</p>
            <p className="mt-1 text-xs text-slate-400 md:text-sm">{t.hero.stat2Label}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-emerald-400 md:text-3xl">{t.hero.stat3Value}</p>
            <p className="mt-1 text-xs text-slate-400 md:text-sm">{t.hero.stat3Label}</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-emerald-400 md:text-3xl">{t.hero.stat4Value}</p>
            <p className="mt-1 text-xs text-slate-400 md:text-sm">{t.hero.stat4Label}</p>
          </div>
        </div>
      </section>

      {/* Telegram Live Bot Banner */}
      <section className="rounded-2xl border border-sky-500/40 bg-gradient-to-r from-sky-950/60 via-slate-900 to-indigo-950/60 p-6 md:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-3 max-w-2xl">
            <div className="flex items-center gap-2">
              <span className="flex h-3 w-3 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-sky-500"></span>
              </span>
              <h2 className="text-xl font-bold text-sky-100 md:text-2xl">{t.telegramBanner.title}</h2>
            </div>
            <p className="text-sm text-slate-300">{t.telegramBanner.desc}</p>
            <div className="grid gap-2 text-xs text-slate-300 sm:grid-cols-2">
              <p dangerouslySetInnerHTML={{ __html: t.telegramBanner.step1 }} />
              <p dangerouslySetInnerHTML={{ __html: t.telegramBanner.step2 }} />
              <p dangerouslySetInnerHTML={{ __html: t.telegramBanner.step3 }} />
              <p dangerouslySetInnerHTML={{ __html: t.telegramBanner.step4 }} />
            </div>
          </div>
          <div className="flex shrink-0 items-center">
            <a
              href="https://t.me/Es0TrustBot"
              target="_blank"
              rel="noreferrer"
              className="inline-flex w-full sm:w-auto items-center justify-center gap-2 rounded-lg bg-sky-500 px-6 py-3.5 text-sm font-bold text-slate-950 shadow-lg shadow-sky-500/30 transition-transform hover:scale-105 hover:bg-sky-400"
            >
              {t.telegramBanner.openBtn} ↗
            </a>
          </div>
        </div>
      </section>

      {/* How It Works (4 Stages) */}
      <section className="space-y-6">
        <div className="text-center">
          <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400">{t.howItWorks.tag}</p>
          <h2 className="mt-1 text-2xl font-bold md:text-3xl">{t.howItWorks.title}</h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-slate-400">{t.howItWorks.subtitle}</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
            <div className="text-2xl"></div>
            <h3 className="font-bold text-slate-100">{t.howItWorks.step1Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.howItWorks.step1Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
            <div className="text-2xl"></div>
            <h3 className="font-bold text-slate-100">{t.howItWorks.step2Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.howItWorks.step2Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
            <div className="text-2xl"></div>
            <h3 className="font-bold text-slate-100">{t.howItWorks.step3Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.howItWorks.step3Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-2">
            <div className="text-2xl"></div>
            <h3 className="font-bold text-slate-100">{t.howItWorks.step4Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.howItWorks.step4Desc}</p>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="space-y-6">
        <div className="text-center">
          <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400">{t.features.tag}</p>
          <h2 className="mt-1 text-2xl font-bold md:text-3xl">{t.features.title}</h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
            <h3 className="font-bold text-slate-100">{t.features.f1Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.features.f1Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
            <h3 className="font-bold text-slate-100">{t.features.f2Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.features.f2Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
            <h3 className="font-bold text-slate-100">{t.features.f3Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.features.f3Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
            <h3 className="font-bold text-slate-100">{t.features.f4Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.features.f4Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
            <h3 className="font-bold text-slate-100">{t.features.f5Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.features.f5Desc}</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-2">
            <h3 className="font-bold text-slate-100">{t.features.f6Title}</h3>
            <p className="text-xs text-slate-400 leading-relaxed">{t.features.f6Desc}</p>
          </div>
        </div>
      </section>

      {/* Bottom CTA Card */}
      <section className="rounded-2xl border border-emerald-500/40 bg-gradient-to-r from-emerald-950/60 to-slate-900 p-8 text-center space-y-4">
        <h2 className="text-2xl font-bold text-emerald-100 md:text-3xl">Ready to test the live physical oracle?</h2>
        <p className="mx-auto max-w-xl text-sm text-slate-300">
          Connect your wallet, snap a photo or input meter data, and watch it anchor onto Solana Devnet in real time.
        </p>
        <div className="pt-2">
          <button
            type="button"
            onClick={onLaunchApp}
            className="rounded-lg bg-emerald-500 px-8 py-3.5 text-base font-bold text-slate-950 shadow-lg shadow-emerald-500/30 transition-transform hover:scale-105 hover:bg-emerald-400"
          >
            {t.hero.ctaPrimary} &rarr;
          </button>
        </div>
      </section>
    </div>
  );
}
