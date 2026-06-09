/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17202a",
        paper: "#f7f8f5",
        line: "#d8ddd2",
        civic: "#1d6f6f",
        saffron: "#d59b2d",
        oxblood: "#8e3b46"
      }
    }
  },
  plugins: []
};
