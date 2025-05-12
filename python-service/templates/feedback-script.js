// feedback-script.js - This will be injected into the HTML
// This script will be loaded directly from the generated HTML, no CORS needed

// Create a function to set up the feedback form
function setupFeedbackForm() {
  // Wait 30 seconds before showing the feedback form
  setTimeout(() => {
    // Check if the feedback popup already exists
    if (!document.getElementById('cc-feedback-container')) {
      // Create the form container
      const container = document.createElement('div');
      container.id = 'cc-feedback-container';
      container.style.cssText = `
        position: fixed;
        bottom: 0;
        right: 0;
        width: 100%;
        max-width: 400px;
        background: white;
        border-radius: 8px 8px 0 0;
        box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.15);
        padding: 20px;
        z-index: 9999;
        transform: translateY(100%);
        opacity: 0;
        transition: transform 0.5s ease-out, opacity 0.5s ease-out;
      `;
      
      // Create the form HTML
      container.innerHTML = `
        <h3 style="font-size: 18px; font-weight: 600; color: #333; margin-bottom: 15px; text-align: center;">Share Your Feedback</h3>
        
        <form id="embedded-feedback-form">
          <div style="margin-bottom: 15px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: #555; margin-bottom: 5px;">Feedback Type</label>
            <select id="feedback-type" name="feedbackType" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px;">
              <option value="Suggestion">Suggestion / Idea</option>
              <option value="Bug">Bug Report</option>
              <option value="Praise">Praise / Compliment</option>
              <option value="Other">Other</option>
            </select>
          </div>
          
          <div style="margin-bottom: 15px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: #555; margin-bottom: 5px;">Your Message <span style="color: #f00;">*</span></label>
            <textarea id="feedback-message" name="message" rows="4" required style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; resize: vertical;" placeholder="Tell us what you think..."></textarea>
            <div style="text-align: right; font-size: 12px; color: #999; margin-top: 2px;"><span id="char-count">0</span>/1000</div>
          </div>
          
          <div style="margin-bottom: 15px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: #555; margin-bottom: 5px;">Rating (Optional)</label>
            <div id="star-rating" style="display: flex; gap: 5px;">
              <button type="button" data-rating="1" style="background: none; border: none; cursor: pointer; color: #ccc; font-size: 24px;">★</button>
              <button type="button" data-rating="2" style="background: none; border: none; cursor: pointer; color: #ccc; font-size: 24px;">★</button>
              <button type="button" data-rating="3" style="background: none; border: none; cursor: pointer; color: #ccc; font-size: 24px;">★</button>
              <button type="button" data-rating="4" style="background: none; border: none; cursor: pointer; color: #ccc; font-size: 24px;">★</button>
              <button type="button" data-rating="5" style="background: none; border: none; cursor: pointer; color: #ccc; font-size: 24px;">★</button>
            </div>
          </div>
          
          <div style="margin-bottom: 20px;">
            <label style="display: block; font-size: 14px; font-weight: 500; color: #555; margin-bottom: 5px;">Your Email (Optional)</label>
            <input type="email" id="feedback-email" name="email" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px;" placeholder="So we can follow up if needed">
          </div>
          
          <button type="submit" id="feedback-submit" style="width: 100%; padding: 12px; background: #F99604; color: white; border: none; border-radius: 4px; font-size: 16px; font-weight: 500; cursor: pointer;">Send Feedback</button>
          
          <div id="feedback-status" style="margin-top: 15px; text-align: center; font-size: 14px;"></div>
        </form>
      `;
      
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
      
      // Add container to body
      document.body.appendChild(container);
      container.appendChild(closeButton);
      
      // Show the popup with animation
      setTimeout(() => {
        container.style.transform = 'translateY(0)';
        container.style.opacity = '1';
      }, 100);
      
      // Add event listener to close button
      closeButton.addEventListener('click', () => {
        container.style.transform = 'translateY(100%)';
        container.style.opacity = '0';
        setTimeout(() => {
          document.body.removeChild(container);
        }, 500);
      });
      
      // Handle character count
      const textarea = container.querySelector('#feedback-message');
      const charCount = container.querySelector('#char-count');
      
      textarea.addEventListener('input', () => {
        const length = textarea.value.length;
        charCount.textContent = length;
        
        if (length > 1000) {
          textarea.value = textarea.value.substring(0, 1000);
          charCount.textContent = 1000;
        }
      });
      
      // Handle star rating
      const starRating = container.querySelector('#star-rating');
      let currentRating = 0;
      
      starRating.addEventListener('click', (e) => {
        const button = e.target.closest('button');
        if (!button) return;
        
        const rating = parseInt(button.dataset.rating);
        currentRating = rating;
        
        // Update star colors
        starRating.querySelectorAll('button').forEach((btn, i) => {
          btn.style.color = i < rating ? '#FFD700' : '#ccc';
        });
      });
      
      // Handle form submission
      const form = container.querySelector('#embedded-feedback-form');
      const submitBtn = container.querySelector('#feedback-submit');
      const statusDiv = container.querySelector('#feedback-status');
      
      form.addEventListener('submit', (e) => {
  e.preventDefault();
  
  const message = textarea.value.trim();
  if (!message) {
    statusDiv.textContent = 'Please enter your feedback message.';
    statusDiv.style.color = '#f44336';
    return;
  }
  
  submitBtn.disabled = true;
  submitBtn.textContent = 'Sending...';
  statusDiv.textContent = '';
  
  // Collect the data
  const feedbackData = {
    feedbackType: container.querySelector('#feedback-type').value,
    message: message,
    email: container.querySelector('#feedback-email').value.trim(),
    rating: currentRating > 0 ? currentRating : undefined,
    source: window.location.href,
    timestamp: new Date().toISOString()
  };
  
  // First save to localStorage
  try {
    const storedFeedback = JSON.parse(localStorage.getItem('ccFeedback') || '[]');
    storedFeedback.push(feedbackData);
    localStorage.setItem('ccFeedback', JSON.stringify(storedFeedback));
  } catch (error) {
    console.error('Error saving to localStorage:', error);
  }
  
  // Create a formData object for the email service
  const formData = new FormData();
  formData.append('access_key', '2b9db55f-5a2a-441a-b7a0-0902b8bce5db'); // Use web3forms.com free service
  formData.append('subject', `Website Feedback: ${feedbackData.feedbackType} from ${window.location.hostname}`);
  formData.append('from_name', 'Website Feedback Form');
  formData.append('reply_to', feedbackData.email || 'noreply@example.com');
  
  // Format the message nicely
  const emailMessage = `
Type: ${feedbackData.feedbackType}
Rating: ${feedbackData.rating || 'Not provided'} out of 5
Source URL: ${feedbackData.source}
User Email: ${feedbackData.email || 'Not provided'}
Time: ${new Date().toLocaleString()}

Message:
${feedbackData.message}
  `;
  
  formData.append('message', emailMessage);
  
  // Submit to Web3Forms service (no CORS issues)
  fetch('https://api.web3forms.com/submit', {
    method: 'POST',
    body: formData
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      // Show success message
      statusDiv.textContent = 'Thank you for your feedback!';
      statusDiv.style.color = '#4CAF50';
      
      // Reset form
      form.reset();
      currentRating = 0;
      charCount.textContent = '0';
      
      // Reset stars
      starRating.querySelectorAll('button').forEach(btn => {
        btn.style.color = '#ccc';
      });
      
      // Hide after delay
      setTimeout(() => {
        closeButton.click();
      }, 3000);
    } else {
      throw new Error(data.message || 'Failed to submit feedback');
    }
  })
  .catch(error => {
    console.error('Error sending feedback:', error);
    // Still show success since we saved to localStorage
    statusDiv.textContent = 'Thank you! Your feedback was saved.';
    statusDiv.style.color = '#4CAF50';
    
    // Reset form after short delay
    setTimeout(() => {
      form.reset();
      currentRating = 0;
      charCount.textContent = '0';
      
      // Reset stars
      starRating.querySelectorAll('button').forEach(btn => {
        btn.style.color = '#ccc';
      });
      
      // Hide the form
      closeButton.click();
    }, 3000);
        })
        .finally(() => {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Send Feedback';
        });
      });
    }
  }, 30000); // 30 seconds
}

// Set up the feedback form when the page loads
document.addEventListener('DOMContentLoaded', setupFeedbackForm);
