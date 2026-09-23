import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
	forgetRememberedCredentials,
	readRememberedCredentials,
	rememberedCredentialsKey,
	rememberSuccessfulCredentials
} from './remembered-credentials';

describe('opt-in browser credentials', () => {
	let values: Map<string, string>;
	const storage = () => ({
		getItem: (key: string) => values.get(key) ?? null,
		setItem: (key: string, value: string) => {
			values.set(key, value);
		},
		removeItem: (key: string) => {
			values.delete(key);
		}
	});
	beforeEach(() => {
		values = new Map();
	});

	it('defaults to no saved credentials', () => {
		expect(readRememberedCredentials('ldap', storage)).toBeUndefined();
		expect(values.size).toBe(0);
	});

	it('saves an opted-in successful login, trimming only the account', () => {
		rememberSuccessfulCredentials('ldap', true, ' MX-TEST ', ' password ', storage);
		expect(readRememberedCredentials('ldap', storage)).toEqual({
			account: 'MX-TEST',
			domainPassword: ' password '
		});
	});

	it('does not remember without opt-in, and clears an existing record', () => {
		rememberSuccessfulCredentials('ldap', true, 'MX-TEST', 'test-password', storage);
		rememberSuccessfulCredentials('ldap', false, 'MX-TEST', 'test-password', storage);
		expect(values.size).toBe(0);
	});

	it('forgets immediately and only affects the selected login method', () => {
		rememberSuccessfulCredentials('ldap', true, 'MX-TEST', 'ldap-password', storage);
		rememberSuccessfulCredentials('signin', true, 'admin@example.test', 'email-password', storage);
		forgetRememberedCredentials('ldap', storage);
		expect(readRememberedCredentials('ldap', storage)).toBeUndefined();
		expect(readRememberedCredentials('signin', storage)?.domainPassword).toBe('email-password');
	});

	it.each([
		'not JSON',
		'null',
		'42',
		'[]',
		'{}',
		JSON.stringify({ account: 123, domainPassword: 'password' }),
		JSON.stringify({ account: '', domainPassword: 'password' }),
		JSON.stringify({ account: '   ', domainPassword: 'password' }),
		JSON.stringify({ account: 'MX\u0000TEST', domainPassword: 'password' }),
		JSON.stringify({ account: 'MX\u007fTEST', domainPassword: 'password' }),
		JSON.stringify({ account: 'x'.repeat(257), domainPassword: 'password' }),
		JSON.stringify({ account: 'MX-TEST', domainPassword: false }),
		JSON.stringify({ account: 'MX-TEST', domainPassword: '' }),
		JSON.stringify({ account: 'MX-TEST', domainPassword: 'x'.repeat(1025) })
	])('discards malformed or invalid stored data (%#)', (value) => {
		values.set(rememberedCredentialsKey('ldap'), value);
		expect(() => readRememberedCredentials('ldap', storage)).not.toThrow();
		expect(values.size).toBe(0);
	});

	it('does not store invalid credentials', () => {
		rememberSuccessfulCredentials('ldap', true, '', 'password', storage);
		expect(values.size).toBe(0);
	});

	it('keeps authentication usable when the storage accessor is blocked', () => {
		const blocked = () => {
			throw new Error('SecurityError');
		};
		expect(readRememberedCredentials('ldap', blocked)).toBeUndefined();
		expect(() => forgetRememberedCredentials('ldap', blocked)).not.toThrow();
		expect(() =>
			rememberSuccessfulCredentials('ldap', true, 'MX-TEST', 'password', blocked)
		).not.toThrow();
	});

	it('ignores storage write failures without logging credential values', () => {
		const log = vi.spyOn(console, 'error');
		const blocked = () => ({
			...storage(),
			setItem: () => {
				throw new Error('QuotaExceededError');
			}
		});
		expect(() =>
			rememberSuccessfulCredentials('ldap', true, 'MX-TEST', 'password', blocked)
		).not.toThrow();
		expect(log).not.toHaveBeenCalled();
		log.mockRestore();
	});
});
