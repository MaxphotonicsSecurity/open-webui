// Matches the MaaS opt-in, successful-login-only browser storage lifecycle.
// LDAP and administrator email credentials are isolated from each other and MaaS.
export type CredentialMode = 'ldap' | 'signin';
export type RememberedCredentials = { account: string; domainPassword: string };
type CredentialStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
type StorageProvider = () => CredentialStorage;
const browserStorage: StorageProvider = () => window.localStorage;

export const rememberedCredentialsKey = (mode: CredentialMode) =>
	`max-chatbot.auth.remembered-credentials.${mode}.v1`;

function validatedCredentials(value: unknown): RememberedCredentials | undefined {
	if (!value || typeof value !== 'object') return;
	const { account, domainPassword } = value as Partial<RememberedCredentials>;
	if (typeof account !== 'string' || typeof domainPassword !== 'string') return;
	const savedAccount = account.trim();
	if (
		!savedAccount ||
		savedAccount.length > 256 ||
		[...savedAccount].some(
			(character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127
		) ||
		!domainPassword ||
		domainPassword.length > 1024
	)
		return;
	return { account: savedAccount, domainPassword };
}

export function forgetRememberedCredentials(mode: CredentialMode, storage = browserStorage) {
	try {
		storage().removeItem(rememberedCredentialsKey(mode));
	} catch {
		// Browser storage may be disabled; authentication remains available.
	}
}

export function readRememberedCredentials(mode: CredentialMode, storage = browserStorage) {
	try {
		const serialized = storage().getItem(rememberedCredentialsKey(mode));
		if (!serialized) return;
		const credentials = validatedCredentials(JSON.parse(serialized));
		if (credentials) return credentials;
	} catch {
		// Corrupt or unavailable browser storage must not prevent sign-in.
	}
	forgetRememberedCredentials(mode, storage);
}

// Call only after the existing authentication API has accepted the credentials.
export function rememberSuccessfulCredentials(
	mode: CredentialMode,
	remember: boolean,
	account: string,
	domainPassword: string,
	storage = browserStorage
) {
	const credentials = validatedCredentials({ account, domainPassword });
	if (!remember || !credentials) {
		forgetRememberedCredentials(mode, storage);
		return;
	}
	try {
		storage().setItem(rememberedCredentialsKey(mode), JSON.stringify(credentials));
	} catch {
		// Do not report an authentication failure when only local storage failed.
	}
}
