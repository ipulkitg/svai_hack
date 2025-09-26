#!/usr/bin/env ts-node
/**
 * Render an MDX document to a static HTML file.
 *
 * Usage: ts-node scripts/renderMdx.ts path/to/tutorial.mdx [--out path/to/output.html]
 */

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import rehypeAutolinkHeadings from "rehype-autolink-headings";
import rehypeSlug from "rehype-slug";
import rehypeStringify from "rehype-stringify";
import remarkFrontmatter from "remark-frontmatter";
import remarkGfm from "remark-gfm";
import remarkMdx from "remark-mdx";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";
import { matter } from "vfile-matter";
import { VFile } from "vfile";

interface CliArgs {
  input: string;
  output?: string;
}

interface TemplateContext {
  title: string;
  bodyHtml: string;
  narrative?: string;
  outcome?: string;
  image?: string;
}

function parseArgs(argv: string[]): CliArgs {
  const args = argv.slice(2);
  if (args.length === 0) {
    console.error("Usage: renderMdx.ts <input.mdx> [--out <output.html>]");
    process.exit(1);
  }
  let input = "";
  let output: string | undefined;
  for (let i = 0; i < args.length; i += 1) {
    const current = args[i];
    if (current === "--out" || current === "-o") {
      const next = args[i + 1];
      if (!next) {
        console.error("Missing value for --out option");
        process.exit(1);
      }
      output = next;
      i += 1;
    } else if (!current.startsWith("-")) {
      input = current;
    }
  }
  if (!input) {
    console.error("Input MDX path is required");
    process.exit(1);
  }
  return { input, output };
}

function buildHtmlTemplate({
  title,
  bodyHtml,
  narrative,
  outcome,
  image,
}: TemplateContext): string {
  const escapedTitle = escapeHtml(title);
  const safeNarrative = narrative ? escapeHtml(narrative) : undefined;
  const safeOutcome = outcome ? escapeHtml(outcome) : undefined;
  const heroMedia = image
    ? `<img src="${escapeHtml(image)}" alt="${escapedTitle} cover" loading="lazy" />`
    : `<div class="image-placeholder" aria-hidden="true"></div>`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapedTitle}</title>
  <style>
    :root {
      color-scheme: light dark;
      --background: 222.2 47.4% 11.2%;
      --foreground: 210 40% 98%;
      --card: 217.2 32.6% 17.5%;
      --card-foreground: 210 40% 98%;
      --muted: 215 20.2% 65.1%;
      --border: 217.2 32.6% 25%;
      --radius: 18;
      font-family: "Inter", "SF Pro Display", "Segoe UI", system-ui, sans-serif;
      background-color: hsl(var(--background));
      color: hsl(var(--foreground));
    }
    body {
      margin: 0;
      min-height: 100vh;
      background: linear-gradient(145deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.92));
      display: flex;
      justify-content: center;
      padding: 3rem 1.5rem 4rem;
    }
    main {
      width: min(1040px, 100%);
      display: grid;
      gap: 1.75rem;
    }
    .card {
      background: hsl(var(--card));
      color: hsl(var(--card-foreground));
      border: 1px solid hsla(var(--border), 0.6);
      border-radius: calc(var(--radius) * 1px);
      box-shadow: 0 22px 45px rgba(8, 12, 32, 0.45);
      padding: 1.75rem;
    }
    .hero {
      display: grid;
      gap: 1.5rem;
    }
    .hero-media {
      position: relative;
      overflow: hidden;
      border-radius: calc(var(--radius) * 0.85px);
    }
    .hero-media img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .image-placeholder {
      width: 100%;
      aspect-ratio: 16 / 9;
      background: radial-gradient(circle at 20% 20%, rgba(94, 234, 212, 0.25), transparent),
        radial-gradient(circle at 80% 0%, rgba(59, 130, 246, 0.25), transparent),
        rgba(30, 41, 59, 0.75);
    }
    .hero-content h1 {
      font-size: clamp(2rem, 4vw, 2.8rem);
      margin: 0 0 1rem;
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 0.72rem;
      color: hsla(var(--muted), 0.9);
      font-weight: 600;
      margin-bottom: 0.75rem;
    }
    .muted {
      color: hsla(var(--muted), 0.92);
      line-height: 1.7;
    }
    .layout {
      display: grid;
      gap: 1.75rem;
    }
    .steps-card h2,
    .outcome-card h2 {
      margin: 0 0 1rem;
      font-size: 1.4rem;
    }
    .steps-content {
      color: inherit;
      line-height: 1.75;
    }
    .steps-content h2,
    .steps-content h3,
    .steps-content h4 {
      margin-top: 2rem;
      margin-bottom: 0.75rem;
    }
    .steps-content p {
      margin: 1rem 0;
    }
    .steps-content ol {
      padding-left: 1.5rem;
      margin: 1rem 0;
      counter-reset: step;
    }
    .steps-content ol > li {
      counter-increment: step;
      margin-bottom: 0.85rem;
      position: relative;
      padding-left: 0.5rem;
    }
    .steps-content ul {
      padding-left: 1.25rem;
      margin: 1rem 0;
    }
    .steps-content pre {
      background: rgba(15, 23, 42, 0.65);
      border-radius: 12px;
      padding: 1rem;
      overflow-x: auto;
    }
    .steps-content code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      font-size: 0.95rem;
    }
    .outcome-card {
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    .outcome-card p {
      margin: 0;
    }
    @media (min-width: 920px) {
      body {
        padding: 4rem 2.5rem 5rem;
      }
      .hero {
        grid-template-columns: minmax(0, 360px) minmax(0, 1fr);
        align-items: center;
      }
      .hero-media {
        height: 100%;
      }
      .layout {
        grid-template-columns: minmax(0, 1fr) minmax(0, 320px);
        align-items: start;
      }
    }
  </style>
</head>
<body>
  <main>
    <section class="card hero">
      <div class="hero-media">
        ${heroMedia}
      </div>
      <div class="hero-content">
        <h1>${escapedTitle}</h1>
        <p class="eyebrow">Backstory</p>
        <p class="muted">${safeNarrative ?? "Capture a concise backstory in the MDX frontmatter using `summary` or `backstory`."}</p>
      </div>
    </section>
    <div class="layout">
      <section class="card steps-card">
        <h2>Steps &amp; Details</h2>
        <div class="steps-content">
          ${bodyHtml}
        </div>
      </section>
      <aside class="card outcome-card">
        <h2>Outcome</h2>
        <p class="muted">${safeOutcome ?? "Describe the expected outcome in the MDX frontmatter using `outcome` or add an `Outcome` section."}</p>
      </aside>
    </div>
  </main>
</body>
</html>`;
}

async function renderMdx(inputPath: string, outputPath?: string): Promise<void> {
  const mdxPath = path.resolve(process.cwd(), inputPath);
  const mdxRaw = await readFile(mdxPath, "utf8");

  const file = new VFile({ value: mdxRaw, path: mdxPath });
  matter(file, { strip: false });

  const processor = unified()
    .use(remarkParse)
    .use(remarkMdx)
    .use(remarkFrontmatter, ["yaml", "toml"])
    .use(remarkGfm)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeSlug)
    .use(rehypeAutolinkHeadings, { behavior: "wrap" })
    .use(rehypeStringify, { allowDangerousHtml: true });

  const compiled = await processor.process(file);

  const htmlBody = String(compiled);
  const cleanBody = stripLeadingTitle(htmlBody);
  const metadata = toRecord(file.data.matter);
  const frontmatterTitle = selectString(metadata, "title");
  const title = frontmatterTitle || inferTitleFromBody(htmlBody) || path.basename(mdxPath);
  const summary =
    selectString(metadata, "backstory") ||
    selectString(metadata, "summary") ||
    extractFirstParagraph(cleanBody);
  const outcome = selectString(metadata, "outcome") || extractOutcome(htmlBody);
  const image = selectString(metadata, "image") || selectString(metadata, "cover");

  const document = buildHtmlTemplate({
    title,
    bodyHtml: cleanBody,
    narrative: summary,
    outcome,
    image,
  });
  const targetPath = outputPath
    ? path.resolve(process.cwd(), outputPath)
    : replaceExtension(mdxPath, ".html");

  await writeFile(targetPath, document, "utf8");
  console.log(`Rendered ${mdxPath} → ${targetPath}`);
}

function replaceExtension(filename: string, extension: string): string {
  return filename.replace(/\.[^.]+$/, extension);
}

function inferTitleFromBody(htmlBody: string): string | undefined {
  const match = htmlBody.match(/<h1[^>]*>(.*?)<\/h1>/i);
  return match ? match[1].replace(/<[^>]+>/g, "").trim() : undefined;
}

function extractFirstParagraph(htmlBody: string): string | undefined {
  const match = htmlBody.match(/<p[^>]*>(.*?)<\/p>/i);
  return match ? stripHtml(match[1]) : undefined;
}

function extractOutcome(htmlBody: string): string | undefined {
  const section = htmlBody.match(/<h[23][^>]*>\s*Outcome\s*<\/h[23]>([\s\S]*?)(<h[23][^>]*>|$)/i);
  if (!section) {
    return undefined;
  }
  const paragraph = section[1].match(/<p[^>]*>(.*?)<\/p>/i);
  return paragraph ? stripHtml(paragraph[1]) : stripHtml(section[1]);
}

function stripLeadingTitle(htmlBody: string): string {
  return htmlBody.replace(/^\s*<h1[^>]*>[\s\S]*?<\/h1>/i, "").trim();
}

function stripHtml(value: string): string {
  return value.replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function selectString(source: Record<string, unknown>, key: string): string | undefined {
  const candidate = source[key];
  return typeof candidate === "string" && candidate.trim() ? candidate.trim() : undefined;
}

(async () => {
  try {
    const { input, output } = parseArgs(process.argv);
    await renderMdx(input, output);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
  }
})();
