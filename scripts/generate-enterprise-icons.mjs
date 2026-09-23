// Regenerate deployment assets from the approved, transparent source icon.
// Usage: node scripts/generate-enterprise-icons.mjs static/static/favicon.svg
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const source = process.argv[2];
if (!source) throw new Error('Provide the approved source SVG or PNG path.');
const root = fileURLToPath(new URL('../', import.meta.url));
const sourceImage = await fs.readFile(source);
const directories = ['static/static', 'backend/open_webui/static'];
const sizes = {
	'favicon.png': 96,
	'favicon-96x96.png': 96,
	'apple-touch-icon.png': 180,
	'web-app-manifest-192x192.png': 192,
	'web-app-manifest-512x512.png': 512,
	'logo.png': 512,
	'splash.png': 256,
	'splash-dark.png': 256
};

for (const [file, size] of Object.entries(sizes)) {
	const png = await sharp(sourceImage).resize(size, size).png().toBuffer();
	for (const directory of directories) await fs.writeFile(path.join(root, directory, file), png);
}
await fs.copyFile(
	path.join(root, 'static/static/favicon.png'),
	path.join(root, 'static/favicon.png')
);

// Preserve approved vector artwork and its attribution without rasterizing the SVG.
const png = await sharp(sourceImage).resize(256, 256).png().toBuffer();
const svg =
	path.extname(source).toLowerCase() === '.svg'
		? sourceImage
		: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><image width="256" height="256" href="data:image/png;base64,${png.toString('base64')}"/></svg>\n`;

// ICO stores PNG frames for crisp browser/tab icons at multiple densities.
const frames = await Promise.all(
	[16, 32, 48, 256].map(async (size) => ({
		size,
		png: await sharp(sourceImage).resize(size, size).png().toBuffer()
	}))
);
const header = Buffer.alloc(6 + frames.length * 16);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(frames.length, 4);
let offset = header.length;
frames.forEach(({ size, png }, index) => {
	const entry = 6 + index * 16;
	header[entry] = header[entry + 1] = size === 256 ? 0 : size;
	header.writeUInt16LE(1, entry + 4);
	header.writeUInt16LE(32, entry + 6);
	header.writeUInt32LE(png.length, entry + 8);
	header.writeUInt32LE(offset, entry + 12);
	offset += png.length;
});
const ico = Buffer.concat([header, ...frames.map(({ png }) => png)]);
for (const directory of directories) {
	await fs.writeFile(path.join(root, directory, 'favicon.svg'), svg);
	await fs.writeFile(path.join(root, directory, 'favicon.ico'), ico);
}
console.log('Generated matching PNG, SVG, ICO, splash and app icons in both static directories.');
