/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  // /api/* is served by the Python serverless function in api/index.py;
  // routing for it is configured in vercel.json.
  webpack: (config, { dev }) => {
    // Local-only guard: if this repo sits on an exFAT/FAT volume on Windows,
    // fs.readlink on a regular file returns EISDIR and webpack's persistent
    // cache snapshotting blows up during `next build`. Vercel builds on Linux
    // ext4 and is unaffected, so scope the workaround to win32.
    if (process.platform === "win32") {
      config.resolve.symlinks = false;
      if (!dev) config.cache = false;
    }
    return config;
  },
};

module.exports = nextConfig;
