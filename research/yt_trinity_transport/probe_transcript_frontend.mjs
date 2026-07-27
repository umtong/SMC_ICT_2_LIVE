#!/usr/bin/env node

/**
 * Exercise a public transcript frontend exactly as an ordinary browser user.
 *
 * This is an evidence probe, not a bulk scraper.  Each configured service is
 * submitted one public representative video.  Success requires transcript-like
 * timestamped/Korean content in the rendered page or a JSON network response;
 * a marketing page, a generic success toast, or video metadata never passes.
 */

import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright';

const serviceSlug = process.argv[2];
const outputDir = path.resolve(process.argv[3] ?? `artifact/frontend-${serviceSlug ?? 'unknown'}`);
const sampleUrl = process.argv[4] ?? 'https://www.youtube.com/watch?v=-Tp2fhvVVGM';

const SERVICES = {
  quicktranscript: {
    url: 'https://quicktranscript.ai/',
    button: /get transcript|try it free|fetch transcript|generate transcript/i,
  },
  transcriptube: {
    url: 'https://transcriptube.com/',
    button: /get transcript|fetch transcript|generate transcript/i,
  },
  scribetube: {
    url: 'https://scribetube.app/',
    button: /get transcript|fetch transcript|generate transcript/i,
  },
  citeclip: {
    url: 'https://citeclip.com/free-tools/youtube-transcript-search',
    button: /get transcript|fetch transcript|search transcript/i,
  },
  pastecontext: {
    url: 'https://pastecontext.com/',
    button: /fetch transcript|fetch context|get transcript/i,
  },
  memra: {
    url: 'https://memra.dostumamigo.com/youtube-transcript',
    button: /get transcript|fetch transcript|generate transcript/i,
  },
};

if (!serviceSlug || !(serviceSlug in SERVICES)) {
  console.error(`usage: ${process.argv[1]} <${Object.keys(SERVICES).join('|')}> <output-dir> [youtube-url]`);
  process.exit(2);
}

function sanitizeName(value) {
  return value.replace(/[^a-zA-Z0-9._-]+/g, '_').slice(0, 160);
}

function errorRecord(error) {
  const value = error instanceof Error ? error : new Error(String(error));
  return {
    name: value.name,
    message: value.message,
    stack_tail: String(value.stack ?? '').split('\n').slice(-12).join('\n'),
  };
}

function transcriptSignals(text) {
  const normalized = String(text ?? '').replace(/\s+/g, ' ').trim();
  const koreanChars = (normalized.match(/[가-힣]/g) ?? []).length;
  const timestampMatches = normalized.match(/(?:^|\s)(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\s|$)/g) ?? [];
  const transcriptWords = normalized.match(/transcript|자막|timestamp|copy transcript|download transcript/gi) ?? [];
  const errorWords = normalized.match(/no captions|no transcript|failed|error|없습니다|찾을 수 없|지원하지 않/gi) ?? [];
  return {
    length: normalized.length,
    korean_chars: koreanChars,
    timestamp_count: timestampMatches.length,
    transcript_word_count: transcriptWords.length,
    error_word_count: errorWords.length,
    excerpt: normalized.slice(0, 4000),
  };
}

async function findInput(page) {
  const selectors = [
    'input[type="url"]',
    'input[placeholder*="YouTube" i]',
    'input[placeholder*="youtube" i]',
    'input[placeholder*="video" i]',
    'input[type="text"]',
    'textarea',
  ];
  for (const selector of selectors) {
    const candidates = page.locator(selector);
    const count = await candidates.count();
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      if (await candidate.isVisible().catch(() => false)) return candidate;
    }
  }
  return null;
}

async function findSubmit(page, pattern) {
  const roles = [
    page.getByRole('button', { name: pattern }),
    page.locator('button[type="submit"]'),
    page.locator('input[type="submit"]'),
  ];
  for (const candidates of roles) {
    const count = await candidates.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const candidate = candidates.nth(index);
      if (await candidate.isVisible().catch(() => false)) return candidate;
    }
  }
  return null;
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const config = SERVICES[serviceSlug];
  const browser = await chromium.launch({
    headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const context = await browser.newContext({
    locale: 'ko-KR',
    timezoneId: 'Asia/Seoul',
    viewport: { width: 1440, height: 1000 },
    userAgent:
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ' +
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
  });
  const page = await context.newPage();
  const network = [];
  let responseCounter = 0;

  page.on('response', async (response) => {
    const request = response.request();
    const resourceType = request.resourceType();
    const url = response.url();
    const contentType = String(response.headers()['content-type'] ?? '');
    const interesting =
      resourceType === 'xhr' ||
      resourceType === 'fetch' ||
      /transcript|caption|youtube|video|api/i.test(url) ||
      /json|text\/plain|vtt|srt/i.test(contentType);
    if (!interesting) return;

    const record = {
      sequence: responseCounter,
      url,
      method: request.method(),
      resource_type: resourceType,
      status: response.status(),
      content_type: contentType,
      request_post_data: request.postData()?.slice(0, 20000) ?? null,
    };
    responseCounter += 1;
    try {
      const body = await response.body();
      record.body_bytes = body.byteLength;
      const truncated = body.subarray(0, 2_000_000);
      const filename = `${String(record.sequence).padStart(3, '0')}-${sanitizeName(new URL(url).hostname)}.body`;
      await writeFile(path.join(outputDir, filename), truncated);
      record.body_file = filename;
      record.body_truncated = body.byteLength > truncated.byteLength;
      if (/json|text|vtt|srt|javascript/i.test(contentType)) {
        const decoded = truncated.toString('utf8');
        record.body_signals = transcriptSignals(decoded);
      }
    } catch (error) {
      record.body_error = errorRecord(error);
    }
    network.push(record);
  });

  const result = {
    schema_version: 1,
    generated_at_utc: new Date().toISOString(),
    service: serviceSlug,
    service_url: config.url,
    sample_url: sampleUrl,
    runtime: {
      node: process.version,
      platform: process.platform,
      arch: process.arch,
      github_run_id: process.env.GITHUB_RUN_ID ?? null,
      github_sha: process.env.GITHUB_SHA ?? null,
    },
    navigation_ok: false,
    submitted: false,
    recovered: false,
  };

  try {
    const navigation = await page.goto(config.url, {
      waitUntil: 'domcontentloaded',
      timeout: 60_000,
    });
    result.navigation_ok = Boolean(navigation?.ok());
    result.navigation_status = navigation?.status() ?? null;
    await page.waitForTimeout(2500);

    const input = await findInput(page);
    if (!input) throw new Error('No visible transcript URL input found');
    result.input_placeholder = await input.getAttribute('placeholder');
    await input.fill(sampleUrl);

    const submit = await findSubmit(page, config.button);
    if (!submit) throw new Error('No visible transcript submit button found');
    result.submit_label = (await submit.textContent())?.trim() ?? null;
    await submit.click();
    result.submitted = true;

    const deadline = Date.now() + 65_000;
    let stableRounds = 0;
    let previousLength = 0;
    while (Date.now() < deadline) {
      await page.waitForTimeout(2500);
      const text = await page.locator('body').innerText().catch(() => '');
      const signals = transcriptSignals(text);
      if (signals.length === previousLength) stableRounds += 1;
      else stableRounds = 0;
      previousLength = signals.length;

      // A real Korean transcript normally supplies hundreds of Hangul glyphs,
      // or many timestamp rows.  This threshold deliberately rejects generic
      // marketing copy that happens to contain the word "transcript".
      if (signals.korean_chars >= 250 || signals.timestamp_count >= 12) break;
      if (stableRounds >= 6 && signals.error_word_count > 0) break;
    }

    result.final_url = page.url();
    const bodyText = await page.locator('body').innerText().catch(() => '');
    result.page_signals = transcriptSignals(bodyText);
    await writeFile(path.join(outputDir, 'page.txt'), bodyText.slice(0, 2_000_000), 'utf8');
    await writeFile(path.join(outputDir, 'page.html'), (await page.content()).slice(0, 4_000_000), 'utf8');
    await page.screenshot({ path: path.join(outputDir, 'page.png'), fullPage: true });

    const strongPage =
      result.page_signals.korean_chars >= 250 || result.page_signals.timestamp_count >= 12;
    const strongNetwork = network.some((record) => {
      const signals = record.body_signals;
      if (!signals || record.status >= 400) return false;
      return signals.korean_chars >= 250 || signals.timestamp_count >= 12;
    });
    result.recovered = strongPage || strongNetwork;
    result.decision = result.recovered ? 'TRANSCRIPT_RECOVERED' : 'NO_RECOVERY';
  } catch (error) {
    result.error = errorRecord(error);
    result.decision = 'PROBE_ERROR';
    try {
      const bodyText = await page.locator('body').innerText().catch(() => '');
      result.page_signals = transcriptSignals(bodyText);
      await writeFile(path.join(outputDir, 'page.txt'), bodyText.slice(0, 2_000_000), 'utf8');
      await page.screenshot({ path: path.join(outputDir, 'page.png'), fullPage: true });
    } catch {
      // Preserve the primary error.
    }
  } finally {
    result.network = network;
    await writeFile(path.join(outputDir, 'probe.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    await browser.close();
  }

  console.log(JSON.stringify({
    service: serviceSlug,
    decision: result.decision,
    recovered: result.recovered,
    page_signals: result.page_signals,
    network_responses: network.length,
  }));
}

main().catch(async (error) => {
  await mkdir(outputDir, { recursive: true });
  const payload = {
    schema_version: 1,
    generated_at_utc: new Date().toISOString(),
    service: serviceSlug,
    decision: 'PROBE_FATAL',
    error: errorRecord(error),
  };
  await writeFile(path.join(outputDir, 'probe.json'), `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  console.error(error);
  process.exitCode = 1;
});
