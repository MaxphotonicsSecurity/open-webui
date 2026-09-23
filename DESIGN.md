---
version: alpha
name: MAX chatbot
description: Enterprise AI workspace with a source-aligned MaaS sign-in surface.
colors:
  primary: '#175cff'
  primary-hover: '#0b4be0'
  ink: '#182238'
  muted: '#556176'
  border: 'rgba(179, 194, 215, 0.72)'
  surface: '#ffffff'
  danger: '#c73535'
typography:
  body:
    fontFamily: 'MaaS Inter, PingFang SC, Microsoft YaHei, system-ui, -apple-system, sans-serif'
  heading:
    fontFamily: 'MaaS Inter, PingFang SC, Microsoft YaHei, system-ui, -apple-system, sans-serif'
rounded:
  control: '8px'
  card: '30px'
spacing:
  page-max: '784px'
  panel: '30px'
components:
  enterprise-login:
    backgroundColor: '#ffffff'
    textColor: '#182238'
---

# Enterprise branding

## Overview

The employee sign-in page ports the supplied ai-MaaS login source: the same glass split card, complete pale blue/cyan background, typography and responsive breakpoints. The approved Sky chatbot SVG replaces the earlier generated mark. Brand and positioning copy identify MAX chatbot as the employee AI assistant.

The latest user request explicitly requires browser-local account/password remembering with the MaaS lifecycle. This replaces the earlier no-password-storage design rule. Existing authentication APIs and permissions remain authoritative; browser storage changes convenience, not authentication.

Runtime CSS is canonical (Model B), owned by `src/lib/components/auth/EnterpriseLogin.svelte`. Reference sources are ai-MaaS `apps/portal-web/src/features/auth/LoginPage.vue` and `src/design-system/tokens.css`. Chat/admin surfaces retain their existing themes.

## Colors

Login CSS uses the MaaS names: `--login-brand` → primary, `--login-brand-hover` → primary-hover, `--login-ink` → ink, `--login-ink-soft` → muted, `--login-line` → border. Error color is #c73535 and glass is white at 64% opacity. The full source gradients, white edge highlights and blurred blue/cyan glows are retained. Authentication stays light in every app theme.

## Typography

Use the MaaS Inter, PingFang SC, Microsoft YaHei, system-ui, -apple-system, sans-serif stack, 14px base with normal line-height and antialiased rendering. Runtime uses a local-only `MaaS Inter` alias (`src: local('Inter')`) to prevent Open WebUI's bundled Inter from replacing MaaS's system fallback. No new remote font requests. Heading is 25px/1.28, brand is 22px/740, hero is 28px/1.4/740, labels are 12px/680, inputs are 14px. Supporting text follows the source's 9–11px hierarchy, as explicitly requested.

## Layout

Desktop card: 784 × 520px, equal columns. Hero padding: 30px 32px 28px. Form padding: 26px 30px 22px. Page uses MaaS viewport gutters, -6px desktop shift, and exact compact/short-window overrides. At 820px it stacks; at 520px it fills the viewport.

The login owns document scroll lock while mounted and releases it on leaving. In very short viewports (≤500px) or with optional extra auth content, the form scrolls internally so actions remain reachable. The small administrator action does not alter the standard form geometry; on extended forms it returns to normal flow.

## Elevation & Depth

The source's glass blur (34px), saturate (132%), multi-layer card shadow, divider and three background glow layers are retained. No new visual treatment is applied to chat.

## Shapes

30px desktop card corners, 26px compact, no corners on mobile; 8px fields/buttons. The user-provided SVG has a translucent sky-blue speech bubble and friendly face. Preserve vector bytes, transparency and colors across themes; do not invert the mark.

## Components

| Capability         | Canonical owner                                  | Source of truth               | Allowed variants                | Verification                                                    |
| ------------------ | ------------------------------------------------ | ----------------------------- | ------------------------------- | --------------------------------------------------------------- |
| Authentication     | `src/routes/auth/+page.svelte`                   | Existing auth APIs            | LDAP and email                  | Success, failure, sessions, redirects                           |
| Form               | `src/lib/components/auth/EnterpriseLogin.svelte` | MaaS login port               | Enterprise / administrator      | Labels, validation, focus, busy state                           |
| Password           | `EnterpriseLogin.svelte`                         | MaaS password control         | Masked / revealed               | Toggle, submit/visibility clear, mode isolation                 |
| Credential storage | `src/lib/utils/remembered-credentials.ts`        | User request + MaaS lifecycle | Separate LDAP/email records     | Opt-in, success-only save, load, clear, corrupt/blocked storage |
| Toast              | Root svelte-sonner provider                      | Existing root layout          | Session success                 | Single global provider; inline login failures                   |
| Scrollbar          | `src/app.css`                                    | Existing global CSS           | Login-scoped overflow ownership | Short/narrow viewports, document restoration                    |
| Locale             | `src/lib/i18n/index.ts`                          | Existing provider             | Chinese / fallback English      | Visible copy and accessible labels                              |

The enterprise password control intentionally uses MaaS markup and eye artwork instead of the general SensitiveInput variant, to satisfy the exact-source geometry requirement. Other screens retain SensitiveInput unchanged from the earlier customization.

LDAP remains the initial mode. Email is available only when server configuration permits it. Switching modes clears transient state then reads that mode's saved record; credentials are never carried across methods. Existing onboarding, trusted-header, OAuth and non-LDAP flows are preserved.

Approved `static/static/favicon.svg` is canonical vector artwork. `scripts/generate-enterprise-icons.mjs` packages raster/ICO sizes into both static mirrors and root favicon. Preserve source attribution. User/model-specific avatars are not replaced.

## Do's and Don'ts

- Keep employee login primary and administrator access quiet but keyboard accessible.
- Save account/password only after opt-in and successful authentication; unchecking immediately removes that mode's record.
- Mask saved passwords; clear transient passwords on submission, visibility loss and unmount. Never log or embed them in URLs/toasts.
- localStorage is plaintext browser storage, as requested; do not imply encryption or secure-vault protection.
- Do not claim verified directory connectivity from a decorative signal.
- Do not restore suggestions, About, changelog modals or update requests through persisted preferences.
