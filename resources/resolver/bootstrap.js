import { ResolverPage } from "./page.js";

const payloadElement = document.getElementById("resolver-data");
const rootElement = document.getElementById("resolver-root");
const errorElement = document.getElementById("resolver-client-error");

if (payloadElement && rootElement) {
  try {
    const payload = JSON.parse(payloadElement.textContent);
    const page = new ResolverPage(rootElement, payload);
    page.mount();
    window.CHTOJResolverPage = page;
  } catch (error) {
    if (errorElement) {
      errorElement.hidden = false;
      errorElement.textContent = `Resolver could not start: ${error.message}`;
    }
  }
}
