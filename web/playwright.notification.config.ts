import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./e2e',testMatch:'notification-layout.spec.ts',workers:1,timeout:150000,
 outputDir:'/tmp/navmate-416-443-test-results',reporter:'line',
 use:{baseURL:'http://127.0.0.1:5244',trace:'retain-on-failure'},
 webServer:{command:'VITE_CALCULATION_MODE=local npx vite --host 127.0.0.1 --port 5244 --strictPort',url:'http://127.0.0.1:5244',reuseExistingServer:!process.env.CI}});
