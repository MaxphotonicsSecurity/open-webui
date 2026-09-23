<script lang="ts">
	import { getContext, onMount, tick } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18n } from 'i18next';
	import { APP_NAME, WEBUI_BASE_URL } from '$lib/constants';
	import {
		forgetRememberedCredentials,
		readRememberedCredentials
	} from '$lib/utils/remembered-credentials';

	const i18n = getContext<Writable<I18n>>('i18n');
	export let mode = 'ldap';
	export let ldapUsername = '';
	export let email = '';
	export let password = '';
	export let rememberCredentials = false;
	export let submitting = false;
	export let error = '';
	export let allowEmail = true;
	export let hasCustomFooter = false;
	export let providers: Record<string, string> = {};
	export let onSubmit: () => Promise<void>;

	let loginForm: HTMLFormElement;
	let invalidField = '';
	let showPassword = false;
	$: canSubmit =
		(mode === 'ldap' ? ldapUsername : email).trim().length > 0 &&
		password.length > 0 &&
		!submitting;

	function clearPassword() {
		password = '';
		showPassword = false;
	}

	function restoreCredentials() {
		const saved = readRememberedCredentials(mode === 'ldap' ? 'ldap' : 'signin');
		rememberCredentials = !!saved;
		if (saved) {
			if (mode === 'ldap') ldapUsername = saved.account;
			else email = saved.account;
			password = saved.domainPassword;
		}
	}

	function changeRemember(event: Event) {
		rememberCredentials = (event.currentTarget as HTMLInputElement).checked;
		if (!rememberCredentials) forgetRememberedCredentials(mode === 'ldap' ? 'ldap' : 'signin');
	}

	const submit = async () => {
		if (submitting) return;
		error = '';
		invalidField = '';
		const invalid = loginForm.querySelector<HTMLInputElement>('input:invalid');
		if (invalid || !canSubmit) {
			invalidField = invalid?.id ?? '';
			error = $i18n.t(
				invalid?.validity.typeMismatch
					? 'Enter a valid email address.'
					: 'Complete the required fields to sign in.'
			);
			invalid?.focus();
			return;
		}
		try {
			await onSubmit();
		} finally {
			clearPassword();
			if (error) {
				await tick();
				loginForm.querySelector<HTMLInputElement>('#enterprise-password')?.focus();
			}
		}
	};

	const switchMode = async () => {
		if (submitting) return;
		clearPassword();
		mode = mode === 'ldap' ? 'signin' : 'ldap';
		error = '';
		invalidField = '';
		restoreCredentials();
		await tick();
		loginForm.querySelector<HTMLInputElement>('input')?.focus();
	};

	onMount(() => {
		document.documentElement.classList.add('max-chatbot-login-active');
		document.body.classList.add('max-chatbot-login-active');
		restoreCredentials();
		if (!rememberCredentials) loginForm.querySelector<HTMLInputElement>('input')?.focus();
		document.addEventListener('visibilitychange', clearPassword);
		window.addEventListener('pagehide', clearPassword);
		return () => {
			document.documentElement.classList.remove('max-chatbot-login-active');
			document.body.classList.remove('max-chatbot-login-active');
			document.removeEventListener('visibilitychange', clearPassword);
			window.removeEventListener('pagehide', clearPassword);
			clearPassword();
		};
	});
</script>

<main class="login-page enterprise-auth" id="auth-container">
	<div class="login-page__glow login-page__glow--blue" aria-hidden="true"></div>
	<div class="login-page__glow login-page__glow--cyan" aria-hidden="true"></div>
	<div class="login-page__glow login-page__glow--right" aria-hidden="true"></div>
	<div class="login-layout">
		<section class="login-hero" aria-labelledby="platform-title">
			<div class="login-hero__brand">
				<div class="login-hero__mark" aria-hidden="true">
					<img
						src="{WEBUI_BASE_URL}/static/favicon.svg?v=max-chatbot-2"
						alt=""
						width="40"
						height="40"
					/>
				</div>
				<div>
					<strong id="platform-title">{APP_NAME}</strong>
					<span>{$i18n.t('Maxphotonics · Enterprise AI assistant')}</span>
				</div>
			</div>
			<div class="login-hero__copy">
				<p>ENTERPRISE AI ASSISTANT</p>
				<h2>
					{$i18n.t('Knowledge, one question away.')}<br /><span
						>{$i18n.t('Take your work a step further.')}</span
					>
				</h2>
				<small>{$i18n.t('Knowledge Q&A · Writing · Coding · Analysis')}</small>
			</div>
			<div class="login-hero__signal" aria-hidden="true">
				<i></i><span>ENTERPRISE WORKSPACE</span>
			</div>
		</section>

		<section
			class="login-card"
			class:has-extra-auth={Object.keys(providers).length > 0 || hasCustomFooter}
			aria-labelledby="enterprise-login-title"
		>
			<header>
				<p class="login-card__eyebrow">SECURE ACCESS</p>
				<h1 id="enterprise-login-title">
					{mode === 'ldap'
						? $i18n.t('Sign in with your enterprise account')
						: $i18n.t('Administrator email sign-in')}
				</h1>
				<p id="login-description" class="login-card__intro">
					{mode === 'ldap'
						? $i18n.t(
								'Sign in with enterprise LDAP. If selected, your account and password are remembered only in this browser, not saved by the platform backend.'
							)
						: $i18n.t(
								'Use your administrator email and password. If selected, sign-in details are remembered only in this browser.'
							)}
				</p>
			</header>

			<form
				bind:this={loginForm}
				novalidate
				on:submit|preventDefault={submit}
				aria-describedby="login-description"
				aria-busy={submitting}
			>
				<div class="login-card__field">
					{#if mode === 'ldap'}
						<label for="enterprise-username">{$i18n.t('Enterprise account')}</label>
						<div
							class="login-card__control"
							class:login-card__control--invalid={invalidField === 'enterprise-username'}
						>
							<input
								id="enterprise-username"
								name="username"
								type="text"
								bind:value={ldapUsername}
								autocomplete="username"
								autocapitalize="none"
								spellcheck="false"
								required
								readonly={submitting}
								placeholder={$i18n.t('Employee ID')}
								aria-invalid={invalidField === 'enterprise-username'}
								aria-describedby={error ? 'enterprise-login-error' : undefined}
							/>
						</div>
					{:else}
						<label for="enterprise-email">{$i18n.t('Email')}</label>
						<div
							class="login-card__control"
							class:login-card__control--invalid={invalidField === 'enterprise-email'}
						>
							<input
								id="enterprise-email"
								name="email"
								type="email"
								bind:value={email}
								autocomplete="username"
								autocapitalize="none"
								spellcheck="false"
								required
								readonly={submitting}
								placeholder={$i18n.t('Enter Your Email')}
								aria-invalid={invalidField === 'enterprise-email'}
								aria-describedby={error ? 'enterprise-login-error' : undefined}
							/>
						</div>
					{/if}
				</div>
				<div class="login-card__field">
					<label for="enterprise-password"
						>{mode === 'ldap' ? $i18n.t('Domain password') : $i18n.t('Password')}</label
					>
					<div
						class="login-card__control login-card__control--password"
						class:login-card__control--invalid={!!error &&
							invalidField !== 'enterprise-email' &&
							invalidField !== 'enterprise-username'}
					>
						<input
							id="enterprise-password"
							name="password"
							type={showPassword ? 'text' : 'password'}
							bind:value={password}
							autocomplete="current-password"
							placeholder={$i18n.t('Password')}
							readonly={submitting}
							required
							aria-invalid={(!!error && !invalidField) || invalidField === 'enterprise-password'}
							aria-describedby={error ? 'enterprise-login-error' : undefined}
						/>
						<button
							class="login-card__password-toggle"
							type="button"
							aria-label={showPassword
								? $i18n.t('Hide password')
								: $i18n.t('Make password visible in the user interface')}
							aria-controls="enterprise-password"
							aria-pressed={showPassword}
							disabled={submitting}
							on:click={() => (showPassword = !showPassword)}
						>
							<svg viewBox="0 0 24 24" aria-hidden="true">
								{#if showPassword}
									<path d="m4 4 16 16" />
									<path
										d="M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 5.2A10.8 10.8 0 0 1 12 5c5.2 0 8.4 5.3 8.4 5.3.4.6.4 1.4 0 2 0 0-.8 1.2-2 2.6M6.6 6.7C4.5 8.2 3.2 10.3 3.2 10.3c-.4.6-.4 1.4 0 2 0 0 3.2 5.3 8.8 5.3 1 0 2-.2 2.8-.5"
									/>
								{:else}
									<path
										d="M3.2 10.3S6.4 5 12 5s8.8 5.3 8.8 5.3c.4.6.4 1.4 0 2 0 0-3.2 5.3-8.8 5.3s-8.8-5.3-8.8-5.3c-.4-.6-.4-1.4 0-2Z"
									/>
									<circle cx="12" cy="11.3" r="2.7" />
								{/if}
							</svg>
						</button>
					</div>
				</div>
				<label class="login-card__remember">
					<input
						name="remember"
						type="checkbox"
						checked={rememberCredentials}
						on:change={changeRemember}
						disabled={submitting}
					/>
					<span
						>{$i18n.t('Remember account and password')}
						<small>{$i18n.t('Only in this browser')}</small></span
					>
				</label>
				<div class="login-card__feedback">
					{#if submitting}<p class="login-card__status" role="status" aria-live="polite">
							{$i18n.t('Authenticating, please wait…')}
						</p>{/if}
					{#if error}<p
							id="enterprise-login-error"
							class="login-card__error"
							role="alert"
							aria-live="assertive"
						>
							{error}
						</p>{/if}
				</div>
				<button class="login-card__submit" type="submit" disabled={!canSubmit}>
					<span>{submitting ? $i18n.t('Authenticating…') : $i18n.t('Sign in to the platform')}</span
					>
				</button>
			</form>
			{#if Object.keys(providers).length > 0}
				<div class="provider-actions">
					{#each Object.entries(providers) as [provider, label]}
						<a href="{WEBUI_BASE_URL}/oauth/{encodeURIComponent(provider)}/login"
							>{$i18n.t('Continue with {{provider}}', { provider: label })}</a
						>
					{/each}
				</div>
			{/if}
			<p class="login-card__support">
				<span
					>{$i18n.t(
						'For authentication issues, contact the Group Information Security Department.'
					)}</span
				>
				<strong>颜明豪-MX19965 · 吴明东-MX19968</strong>
			</p>
			{#if allowEmail}
				<button class="login-card__admin" type="button" on:click={switchMode} disabled={submitting}>
					{mode === 'ldap'
						? $i18n.t('Administrator access')
						: $i18n.t('Back to enterprise sign-in')}
				</button>
			{/if}
			<div class="custom-footer"><slot /></div>
		</section>
	</div>
</main>

<style>
	/* Visual source: ai-MaaS/apps/portal-web/src/features/auth/LoginPage.vue.
	   Keep MaaS dimensions, gradients, typography and responsive rules together. */

	.login-page {
		--login-brand: #175cff;
		--login-brand-hover: #0b4be0;
		--login-ink: #182238;
		--login-ink-soft: #556176;
		--login-line: rgb(179 194 215 / 72%);
		--login-glass: rgb(255 255 255 / 64%);
		--login-gutter-x: clamp(18px, calc((100vw - 784px) / 2), 112px);
		--login-gutter-y: clamp(24px, 4.5vh, 48px);
		position: fixed;
		inset: 0;
		isolation: isolate;
		width: 100%;
		height: 100vh;
		height: 100dvh;
		min-height: 0;
		display: grid;
		place-items: center;
		box-sizing: border-box;
		overflow: hidden;
		padding: var(--login-gutter-y) var(--login-gutter-x);
		background:
			radial-gradient(ellipse 48% 44% at 4% 96%, rgb(93 220 248 / 30%) 0%, transparent 72%),
			radial-gradient(ellipse 42% 48% at 101% 52%, rgb(121 190 255 / 24%) 0%, transparent 72%),
			radial-gradient(ellipse 54% 37% at 28% -4%, rgb(144 158 238 / 22%) 0%, transparent 74%),
			linear-gradient(135deg, #f8faff 0%, #f5f8fe 48%, #f8fbff 100%);
	}

	:global(html.max-chatbot-login-active) {
		height: 100%;
		overflow: hidden;
		scrollbar-gutter: auto;
	}

	:global(body.max-chatbot-login-active),
	:global(body.max-chatbot-login-active #app) {
		width: 100%;
		height: 100%;
		min-height: 0;
		overflow: hidden;
	}

	.login-page__glow {
		position: absolute;
		z-index: -1;
		pointer-events: none;
		border-radius: 46% 54% 58% 42%;
		filter: blur(82px);
	}

	.login-page__glow--blue {
		width: min(58vw, 860px);
		height: min(44vw, 620px);
		top: -28%;
		left: -12%;
		background: rgb(133 155 236 / 24%);
		transform: rotate(-9deg);
	}

	.login-page__glow--cyan {
		width: min(54vw, 820px);
		height: min(42vw, 590px);
		bottom: -24%;
		left: -16%;
		background: rgb(81 222 238 / 26%);
		transform: rotate(12deg);
	}

	.login-page__glow--right {
		width: min(45vw, 680px);
		height: min(58vw, 760px);
		top: 12%;
		right: -20%;
		background: rgb(105 183 255 / 22%);
		transform: rotate(-8deg);
	}

	.login-layout {
		position: relative;
		width: min(100%, 784px);
		height: min(520px, calc(100vh - var(--login-gutter-y) - var(--login-gutter-y)));
		height: min(520px, calc(100dvh - var(--login-gutter-y) - var(--login-gutter-y)));
		min-height: 0;
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		box-sizing: border-box;
		overflow: hidden;
		border: 2px solid rgb(255 255 255 / 90%);
		border-radius: 30px;
		background: var(--login-glass);
		box-shadow:
			0 34px 92px rgb(47 66 100 / 13%),
			0 3px 12px rgb(47 66 100 / 6%),
			inset 0 1px 0 rgb(255 255 255 / 96%),
			inset 0 -1px 0 rgb(127 148 178 / 11%);
		-webkit-backdrop-filter: blur(34px) saturate(132%);
		backdrop-filter: blur(34px) saturate(132%);
		transform: translateY(-6px);
	}

	.login-layout::before {
		position: absolute;
		z-index: 2;
		top: 0;
		right: 28px;
		left: 28px;
		height: 1px;
		background: linear-gradient(
			90deg,
			transparent,
			rgb(255 255 255 / 96%) 16%,
			rgb(255 255 255 / 96%) 84%,
			transparent
		);
		content: '';
		pointer-events: none;
	}

	.login-layout::after {
		position: absolute;
		z-index: 3;
		top: 0;
		bottom: 0;
		left: 50%;
		width: 1px;
		background: linear-gradient(
			180deg,
			rgb(255 255 255 / 64%),
			rgb(152 174 205 / 25%) 14%,
			rgb(152 174 205 / 22%) 86%,
			rgb(255 255 255 / 58%)
		);
		box-shadow: 1px 0 0 rgb(255 255 255 / 46%);
		content: '';
		pointer-events: none;
	}

	.login-hero {
		position: relative;
		min-width: 0;
		min-height: 0;
		padding: 30px 32px 28px;
		display: flex;
		flex-direction: column;
		color: var(--login-ink);
		background: linear-gradient(
			150deg,
			rgb(235 242 255 / 74%) 0%,
			rgb(235 247 255 / 62%) 48%,
			rgb(222 249 251 / 58%) 100%
		);
	}

	.login-hero__brand,
	.login-hero__copy {
		position: relative;
		z-index: 1;
	}

	.login-hero__brand {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.login-hero__mark {
		position: relative;
		width: 56px;
		height: 56px;
		flex: 0 0 56px;
		padding: 8px;
		box-sizing: border-box;
		overflow: hidden;
		border: 1px solid rgb(255 255 255 / 94%);
		border-radius: 17px;
		background: linear-gradient(
			145deg,
			rgb(255 255 255 / 89%),
			rgb(225 241 255 / 54%) 58%,
			rgb(236 232 255 / 46%)
		);
		box-shadow:
			0 13px 30px rgb(58 92 143 / 15%),
			inset 0 1px 0 white,
			inset 0 -1px 0 rgb(86 126 179 / 10%);
		-webkit-backdrop-filter: blur(18px) saturate(138%);
		backdrop-filter: blur(18px) saturate(138%);
	}

	.login-hero__mark::after {
		position: absolute;
		top: 4px;
		right: 9px;
		left: 9px;
		height: 8px;
		border-radius: 999px;
		background: linear-gradient(180deg, rgb(255 255 255 / 62%), transparent);
		content: '';
		pointer-events: none;
	}

	.login-hero__brand > div:last-child {
		display: grid;
		gap: 3px;
	}

	.login-hero__brand strong {
		color: #1c2840;
		font-size: 22px;
		font-weight: 740;
		letter-spacing: -0.035em;
	}

	.login-hero__brand > div:last-child span {
		color: var(--login-ink-soft);
		font-size: 11px;
		letter-spacing: 0.01em;
	}

	.login-hero__copy {
		margin: clamp(48px, 7vh, 64px) 0 0;
		max-width: 328px;
	}

	.login-hero__copy p {
		margin: 0 0 12px;
		color: #075bff;
		font-size: 9px;
		font-weight: 780;
		letter-spacing: 0.24em;
	}

	.login-hero__copy h2 {
		margin: 0;
		color: #13223a;
		font-size: 28px;
		font-weight: 740;
		line-height: 1.4;
		letter-spacing: -0.05em;
	}

	.login-hero__copy h2 span {
		color: inherit;
	}

	.login-hero__copy small {
		margin-top: 12px;
		display: block;
		color: var(--login-ink-soft);
		font-size: 11px;
		line-height: 1.55;
		letter-spacing: 0.005em;
	}

	.login-hero__signal {
		margin-top: auto;
		display: flex;
		align-items: center;
		gap: 8px;
		color: #728199;
		font-size: 9px;
		font-weight: 760;
		letter-spacing: 0.16em;
	}

	.login-hero__signal i {
		width: 7px;
		height: 7px;
		flex: 0 0 7px;
		border-radius: 50%;
		background: #17c9a2;
		box-shadow: 0 0 0 4px rgb(23 201 162 / 8%);
	}

	.login-card {
		position: relative;
		min-width: 0;
		min-height: 0;
		padding: 26px 30px 22px;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		overflow-wrap: anywhere;
		background:
			radial-gradient(ellipse 76% 54% at 112% -4%, rgb(190 214 255 / 34%) 0%, transparent 70%),
			radial-gradient(ellipse 68% 48% at 108% 104%, rgb(199 235 255 / 22%) 0%, transparent 72%),
			linear-gradient(145deg, rgb(255 255 255 / 86%) 0%, rgb(249 252 255 / 74%) 100%);
	}

	.login-card__eyebrow {
		margin: 0 0 6px;
		color: var(--login-brand);
		font-size: 9px;
		font-weight: 780;
		letter-spacing: 0.24em;
	}

	h1 {
		margin: 0;
		color: #111827;
		font-size: 25px;
		line-height: 1.28;
		letter-spacing: -0.045em;
	}

	.login-card__intro {
		max-width: 450px;
		margin: 6px 0 0;
		color: #708099;
		font-size: 11px;
		line-height: 1.5;
	}

	form {
		display: grid;
		gap: 8px;
		margin-top: 16px;
	}

	.login-card__field + .login-card__field {
		margin-top: 0;
	}

	.login-card__field {
		display: grid;
		min-width: 0;
		gap: 4px;
	}

	.login-card__field > label {
		color: #20283a;
		font-size: 12px;
		font-weight: 680;
	}

	.login-card__control {
		width: 100%;
		min-width: 0;
		min-height: 44px;
		display: flex;
		align-items: center;
		box-sizing: border-box;
		overflow: hidden;
		border: 1px solid var(--login-line);
		border-radius: 8px;
		background: rgb(255 255 255 / 58%);
		box-shadow:
			inset 0 1px 0 rgb(255 255 255 / 92%),
			0 1px 2px rgb(46 67 99 / 3%);
		transition:
			border-color var(--maas-motion-fast),
			background var(--maas-motion-fast),
			box-shadow var(--maas-motion-fast);
		-webkit-backdrop-filter: blur(12px);
		backdrop-filter: blur(12px);
	}

	.login-card__control:hover {
		border-color: rgb(142 166 197 / 78%);
		background: rgb(255 255 255 / 76%);
	}

	.login-card__control:focus-within {
		border-color: var(--login-brand);
		background: rgb(255 255 255 / 88%);
		box-shadow:
			0 0 0 3px rgb(23 92 255 / 13%),
			inset 0 1px 0 white;
	}

	.login-card__control--invalid {
		border-color: rgb(199 53 53 / 58%);
	}

	.login-card__control--invalid:focus-within {
		border-color: #c73535;
		box-shadow:
			0 0 0 3px rgb(199 53 53 / 11%),
			inset 0 1px 0 white;
	}

	.login-card__control input {
		width: 100%;
		min-width: 0;
		min-height: 42px;
		box-sizing: border-box;
		padding: 0 15px;
		border: 0;
		outline: 0;
		color: var(--login-ink);
		background: transparent;
		font: inherit;
		font-size: 14px;
	}

	.login-card__control--password input {
		padding-right: 4px;
	}

	.login-card__control input::placeholder {
		color: #8490a5;
		font-size: 14px;
		font-weight: 470;
	}

	.login-card__control input:read-only {
		cursor: wait;
	}

	.login-card__password-toggle {
		width: 44px;
		height: 44px;
		flex: 0 0 44px;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 9px;
		color: #66748a;
		background: transparent;
		cursor: pointer;
		transition:
			color var(--maas-motion-fast),
			background var(--maas-motion-fast);
	}

	.login-card__password-toggle:hover:not(:disabled) {
		color: var(--login-brand);
		background: rgb(234 242 255 / 76%);
	}

	.login-card__password-toggle:active:not(:disabled) {
		background: rgb(220 233 255 / 88%);
	}

	.login-card__password-toggle:focus-visible {
		outline: 2px solid var(--login-brand);
		outline-offset: -4px;
	}

	.login-card__password-toggle:disabled {
		cursor: not-allowed;
		opacity: 0.48;
	}

	.login-card__password-toggle svg {
		width: 17px;
		height: 17px;
		fill: none;
		stroke: currentColor;
		stroke-width: 1.7;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.login-card__remember {
		margin-top: 0;
		min-height: 22px;
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--login-ink-soft);
		font-size: 12px;
		font-weight: 630;
		cursor: pointer;
	}

	.login-card__remember input {
		appearance: none;
		/* MaaS retains the native checkbox margin; Tailwind's reset removes it. */
		margin: revert;
		width: 18px;
		height: 18px;
		min-height: 18px;
		flex: 0 0 18px;
		padding: 0;
		border: 1px solid #bcc8d9;
		border-radius: 6px;
		background: rgb(255 255 255 / 78%);
		cursor: pointer;
	}

	.login-card__remember input:checked {
		border-color: var(--login-brand);
		background: var(--login-brand);
		box-shadow: inset 0 0 0 3px white;
	}

	.login-card__remember input:focus-visible {
		outline: 3px solid rgb(23 92 255 / 24%);
		outline-offset: 2px;
	}

	.login-card__remember small {
		margin-left: 5px;
		color: #7d899c;
		font-size: 10px;
		font-weight: 450;
	}

	.login-card__feedback {
		margin-top: 0;
		min-height: 18px;
		display: flex;
		align-items: flex-start;
	}

	.login-card__status,
	.login-card__error {
		width: 100%;
		margin: 0;
		font-size: 11px;
		line-height: 1.45;
	}

	.login-card__status {
		color: var(--login-ink-soft);
	}

	.login-card__error {
		padding: 5px 8px;
		border: 1px solid rgb(199 53 53 / 16%);
		border-radius: 8px;
		color: #a52f2f;
		background: rgb(255 244 244 / 72%);
	}

	.login-card__submit {
		position: relative;
		margin-top: 0;
		width: 100%;
		min-height: 44px;
		padding: 0 17px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 9px;
		border: 0;
		border-radius: 8px;
		color: white;
		background: var(--login-brand);
		box-shadow: 0 7px 18px rgb(23 92 255 / 18%);
		cursor: pointer;
		font: inherit;
		font-size: 14px;
		font-weight: 720;
		letter-spacing: 0.01em;
		transition:
			background var(--maas-motion-fast),
			box-shadow var(--maas-motion-fast);
	}

	.login-card__submit:hover:not(:disabled) {
		background: var(--login-brand-hover);
		box-shadow: 0 8px 20px rgb(23 92 255 / 23%);
	}

	.login-card__submit:active:not(:disabled) {
		background: #0843c8;
		box-shadow: 0 4px 12px rgb(23 92 255 / 18%);
	}

	.login-card__submit:focus-visible {
		outline: 3px solid var(--maas-color-focus-ring);
		outline-offset: 3px;
	}

	.login-card__submit:disabled {
		cursor: not-allowed;
		box-shadow: none;
		opacity: 0.76;
	}

	.login-card__support {
		margin: auto 0 0;
		padding-top: 8px;
		display: grid;
		gap: 2px;
		color: var(--login-ink-soft);
		font-size: 10px;
		line-height: 1.35;
	}

	.login-card__support::before {
		width: 20px;
		height: 1px;
		margin-bottom: 2px;
		background: rgb(150 171 199 / 38%);
		content: '';
	}

	.login-card__support strong {
		color: #455269;
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.01em;
	}

	@supports not ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))) {
		.login-layout {
			background: #f9fbfd;
		}

		.login-hero {
			background: #edf6fb;
		}

		.login-hero__mark,
		.login-card,
		.login-card__control {
			background: #fff;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.login-card__control,
		.login-card__password-toggle,
		.login-card__submit {
			transition-duration: 0.01ms;
		}
	}

	@media (prefers-reduced-transparency: reduce) {
		.login-page__glow {
			display: none;
		}

		.login-layout,
		.login-hero__mark,
		.login-card,
		.login-card__control {
			-webkit-backdrop-filter: none;
			backdrop-filter: none;
		}

		.login-layout {
			background: #f9fbfd;
		}

		.login-hero {
			background: #edf6fb;
		}

		.login-hero__mark,
		.login-card,
		.login-card__control {
			background: #fff;
		}
	}

	@media (forced-colors: active) {
		.login-page__glow {
			display: none;
		}

		.login-layout,
		.login-hero,
		.login-hero__mark,
		.login-card,
		.login-card__control,
		.login-card__error {
			border-color: CanvasText;
			box-shadow: none;
			-webkit-backdrop-filter: none;
			backdrop-filter: none;
		}

		.login-card__control:focus-within {
			outline: 2px solid Highlight;
			outline-offset: 2px;
		}

		.login-card__remember input {
			appearance: auto;
		}
	}

	@media (max-width: 1099px), (max-height: 839px) {
		.login-layout {
			border-radius: 26px;
			transform: none;
		}
	}

	@media (min-width: 821px) {
		.login-card__feedback {
			min-height: 44px;
		}
	}

	@media (max-width: 820px) {
		.login-page {
			--login-gutter-x: clamp(16px, 4vw, 28px);
			--login-gutter-y: clamp(16px, 3vh, 24px);
			padding: var(--login-gutter-y) var(--login-gutter-x);
			place-items: center;
		}

		.login-layout {
			width: min(100%, 560px);
			height: min(760px, calc(100dvh - var(--login-gutter-y) - var(--login-gutter-y)));
			min-height: 0;
			grid-template-columns: 1fr;
			grid-template-rows: clamp(170px, 25dvh, 180px) minmax(0, 1fr);
		}

		.login-layout::after {
			display: none;
		}

		.login-hero {
			min-height: 0;
			padding: 25px 32px 22px;
		}

		.login-hero__copy {
			margin: 25px 0 0;
		}

		.login-hero__copy h2 {
			font-size: 24px;
			line-height: 1.35;
		}

		.login-hero__copy p,
		.login-hero__copy small {
			display: none;
		}

		.login-hero__signal {
			display: none;
		}

		.login-card {
			min-height: 0;
			padding: 26px 36px 20px;
		}

		.login-card__intro {
			max-width: none;
		}
	}

	@media (min-width: 521px) and (max-width: 820px) {
		form {
			gap: 10px;
			margin-top: 20px;
		}
	}

	@media (max-width: 520px) {
		.login-page {
			--login-gutter-x: 0px;
			--login-gutter-y: 0px;
		}

		.login-page__glow--blue {
			width: 310px;
			height: 250px;
			top: -70px;
			left: -120px;
		}

		.login-page__glow--cyan {
			width: 290px;
			height: 230px;
			bottom: 2%;
			left: -130px;
		}

		.login-layout {
			width: 100%;
			height: 100vh;
			height: 100dvh;
			min-height: 0;
			grid-template-rows: clamp(136px, 22dvh, 174px) minmax(0, 1fr);
			border: 0;
			border-radius: 0;
			box-shadow: none;
		}

		.login-hero {
			min-height: 0;
			padding: 23px 24px 20px;
		}

		.login-hero__mark {
			width: 50px;
			height: 50px;
			flex-basis: 50px;
			padding: 7px;
			border-radius: 15px;
		}

		.login-hero__brand {
			gap: 14px;
		}

		.login-hero__brand strong {
			font-size: 20px;
		}

		.login-hero__brand > div:last-child span {
			font-size: 11px;
		}

		.login-hero__copy {
			margin-top: 20px;
		}

		.login-hero__copy h2 {
			font-size: 21px;
		}

		.login-card {
			min-height: 0;
			padding: 28px 24px max(24px, env(safe-area-inset-bottom));
		}

		h1 {
			font-size: 26px;
		}

		form {
			margin-top: 22px;
		}
	}

	@media (max-height: 700px) {
		.login-page {
			--login-gutter-y: 18px;
			place-items: center;
			padding-block: var(--login-gutter-y);
		}

		.login-layout {
			height: min(520px, calc(100dvh - var(--login-gutter-y) - var(--login-gutter-y)));
			min-height: 0;
		}

		.login-hero {
			min-height: 0;
			padding: 24px 30px 22px;
		}

		.login-hero__mark {
			width: 52px;
			height: 52px;
			flex-basis: 52px;
			padding: 7px;
			border-radius: 16px;
		}

		.login-hero__copy {
			margin-top: 34px;
		}

		.login-hero__copy p {
			display: none;
		}

		.login-hero__copy h2 {
			font-size: 28px;
			line-height: 1.35;
		}

		.login-hero__copy small {
			margin-top: 10px;
			font-size: 10px;
		}

		.login-card {
			min-height: 0;
			padding: 22px 30px 20px;
		}

		.login-card__eyebrow {
			margin-bottom: 5px;
			font-size: 9px;
		}

		h1 {
			font-size: 25px;
		}

		.login-card__intro {
			margin-top: 6px;
			font-size: 10px;
			line-height: 1.45;
		}

		form {
			gap: 9px;
			margin-top: 13px;
		}

		.login-card__field {
			gap: 4px;
		}

		.login-card__field > label {
			font-size: 11px;
		}

		.login-card__control {
			min-height: 44px;
		}

		.login-card__control input {
			min-height: 42px;
			font-size: 13px;
		}

		.login-card__password-toggle {
			width: 42px;
			height: 42px;
			flex-basis: 42px;
		}

		.login-card__remember {
			min-height: 22px;
			font-size: 11px;
		}

		.login-card__feedback {
			min-height: 18px;
		}

		.login-card__status,
		.login-card__error {
			font-size: 10px;
		}

		.login-card__error {
			padding: 5px 8px;
		}

		.login-card__submit {
			min-height: 44px;
			font-size: 13px;
		}

		.login-card__support {
			display: none;
		}
	}

	@media (max-height: 700px) and (max-width: 820px) {
		.login-page {
			--login-gutter-x: clamp(12px, 3vw, 20px);
			--login-gutter-y: 0px;
		}

		.login-layout {
			width: min(100%, 560px);
			height: 100dvh;
			grid-template-columns: 1fr;
			grid-template-rows: 92px minmax(0, 1fr);
			border-radius: 0;
		}

		.login-hero {
			padding: 18px 24px;
			border-bottom: 1px solid rgb(143 166 194 / 15%);
		}

		.login-hero__copy {
			display: none;
		}

		.login-card {
			padding: 20px 26px max(18px, env(safe-area-inset-bottom));
		}
	}

	/* MaaS uses system Inter, not Open WebUI's bundled @font-face. An alias
	   preserves the same system fallback without changing the rest of the app. */
	@font-face {
		font-family: 'MaaS Inter';
		src: local('Inter');
		font-weight: 100 900;
		font-display: swap;
	}
	/* Scope MaaS base tokens/reset to this page; never change the chat theme. */
	.login-page {
		--maas-motion-fast: 140ms;
		--maas-color-focus-ring: #175cff;
		color: #171a21;
		color-scheme: light;
		font-family:
			'MaaS Inter',
			'PingFang SC',
			'Microsoft YaHei',
			system-ui,
			-apple-system,
			sans-serif;
		font-size: 14px;
		line-height: normal;
		-webkit-font-smoothing: antialiased;
	}
	h1 {
		font-weight: 700;
	}
	.login-hero__mark img {
		display: block;
		width: 100%;
		height: 100%;
		object-fit: contain;
	}
	.login-card__remember input:disabled {
		cursor: not-allowed;
	}
	.login-card__admin {
		position: absolute;
		right: 30px;
		bottom: 22px;
		border: 0;
		background: transparent;
		color: #708099;
		padding: 2px 0;
		font: inherit;
		font-size: 9px;
		cursor: pointer;
	}
	.login-card__admin:hover {
		color: var(--login-brand);
		text-decoration: underline;
	}
	.login-card__admin:focus-visible,
	.provider-actions a:focus-visible {
		outline: 2px solid var(--login-brand);
		outline-offset: 3px;
	}
	.login-card__admin:disabled {
		cursor: not-allowed;
		opacity: 0.48;
	}
	.provider-actions {
		display: grid;
		gap: 6px;
		margin-top: 12px;
		font-size: 11px;
		color: var(--login-brand);
	}
	.has-extra-auth {
		overflow-y: auto;
	}
	.has-extra-auth .login-card__admin {
		position: static;
		align-self: flex-end;
		margin-top: 8px;
	}
	@media (max-width: 520px) {
		.login-card__admin {
			right: 24px;
			bottom: max(24px, env(safe-area-inset-bottom));
		}
	}
	/* Keep every action reachable on short viewports / with an on-screen keyboard. */
	@media (max-height: 500px) {
		.login-card {
			display: block;
			overflow-y: auto;
		}
		.login-card__admin {
			position: static;
			display: block;
			margin: 12px 0 0 auto;
		}
	}
</style>
