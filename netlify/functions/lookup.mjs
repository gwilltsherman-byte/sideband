export { default } from '../../server/proxy.mjs';

// Netlify reads routing from the function entry file at build time.
export const config = { path: '/api/proxy' };
