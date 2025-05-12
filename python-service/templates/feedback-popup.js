// feedback-popup.js
document.addEventListener('DOMContentLoaded', () => {
  // Wait 30 seconds before showing the feedback form
  setTimeout(() => {
    // Check if the feedback popup already exists
    if (!document.getElementById('cc-feedback-iframe-container')) {
      // Create the iframe container
      const container = document.createElement('div');
      container.id = 'cc-feedback-iframe-container';
      container.style.cssText = `
        position: fixed;
        bottom: 0;
        right: 0;
        width: 100%;
        max-width: 400px;
        z-index: 9999;
        transform: translateY(100%);
        opacity: 0;
        transition: transform 0.5s ease-out, opacity 0.5s ease-out;
      `;
      
      // Create the iframe
      const iframe = document.createElement('iframe');
      iframe.src = 'https://clickcatalyst.digital/feedback?source=' + encodeURIComponent(window.location.href);
      iframe.style.cssText = `
        width: 100%;
        height: 450px;
        border: none;
        border-radius: 8px 8px 0 0;
        box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.15);
        background: white;
      `;
      
      // Append iframe to container
      container.appendChild(iframe);
      
      // Add container to body
      document.body.appendChild(container);
      
      // Show the popup with animation
      setTimeout(() => {
        container.style.transform = 'translateY(0)';
        container.style.opacity = '1';
      }, 100);
      
      // Add close button
      const closeButton = document.createElement('button');
      closeButton.innerHTML = '&times;';
      closeButton.style.cssText = `
        position: absolute;
        top: 10px;
        right: 10px;
        background: white;
        color: #333;
        border: none;
        border-radius: 50%;
        width: 30px;
        height: 30px;
        font-size: 20px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
      `;
      
      // Add event listener to close button
      closeButton.addEventListener('click', () => {
        container.style.transform = 'translateY(100%)';
        container.style.opacity = '0';
        setTimeout(() => {
          document.body.removeChild(container);
        }, 500);
      });
      
      container.appendChild(closeButton);
    }
  }, 30000); // 30 seconds
});
