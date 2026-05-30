"""
Authentication and session handling for login-based scraping
"""

import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from urllib.parse import urljoin
import asyncio
from playwright.async_api import Page, BrowserContext

logger = logging.getLogger(__name__)

@dataclass
class LoginCredentials:
    username: str
    password: str
    login_url: str
    username_selector: str
    password_selector: str
    submit_selector: str
    success_indicator: Optional[str] = None
    additional_fields: Optional[Dict[str, str]] = None

@dataclass
class CookieProfile:
    name: str
    cookies: List[Dict[str, Any]]
    user_agent: str
    created_at: str

class AuthHandler:
    def __init__(self):
        self.saved_profiles = {}
    
    async def login(self, page: Page, credentials: LoginCredentials) -> bool:
        """
        Perform login using credentials
        """
        try:
            # Navigate to login page
            await page.goto(credentials.login_url)
            await page.wait_for_load_state('networkidle')
            
            # Fill username
            await page.fill(credentials.username_selector, credentials.username)
            
            # Fill password
            await page.fill(credentials.password_selector, credentials.password)
            
            # Fill additional fields if provided
            if credentials.additional_fields:
                for selector, value in credentials.additional_fields.items():
                    await page.fill(selector, value)
            
            # Handle potential form submission delays
            await asyncio.sleep(1)
            
            # Submit form
            await page.click(credentials.submit_selector)
            
            # Wait for navigation or success indicator
            if credentials.success_indicator:
                try:
                    await page.wait_for_selector(credentials.success_indicator, timeout=10000)
                except:
                    # Check if we're still on login page (login failed)
                    current_url = page.url
                    if credentials.login_url in current_url:
                        return False
            else:
                # Wait for navigation to complete
                await page.wait_for_load_state('networkidle', timeout=10000)
            
            # Check if login was successful
            return await self._verify_login(page, credentials)
            
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            return False
    
    async def _verify_login(self, page: Page, credentials: LoginCredentials) -> bool:
        """
        Verify if login was successful
        """
        try:
            # Check if we're still on login page
            current_url = page.url
            if credentials.login_url in current_url:
                return False
            
            # Check for error messages
            error_selectors = [
                '.error', '.alert-danger', '.login-error', 
                '[class*="error"]', '[class*="invalid"]'
            ]
            
            for selector in error_selectors:
                try:
                    error_element = await page.query_selector(selector)
                    if error_element:
                        error_text = await error_element.text_content()
                        if error_text and any(word in error_text.lower() for word in ['error', 'invalid', 'failed', 'incorrect']):
                            return False
                except:
                    continue
            
            # Check for success indicators
            if credentials.success_indicator:
                try:
                    success_element = await page.query_selector(credentials.success_indicator)
                    return success_element is not None
                except:
                    pass
            
            # If no specific indicators, assume success if we're not on login page
            return True
            
        except Exception as e:
            logger.error(f"Login verification failed: {str(e)}")
            return False
    
    async def save_cookies(self, context: BrowserContext, profile_name: str) -> CookieProfile:
        """
        Save cookies and session data
        """
        try:
            cookies = await context.cookies()
            user_agent = await context.evaluate('navigator.userAgent')
            
            profile = CookieProfile(
                name=profile_name,
                cookies=cookies,
                user_agent=user_agent,
                created_at=datetime.utcnow().isoformat()
            )
            
            self.saved_profiles[profile_name] = profile
            
            return profile
            
        except Exception as e:
            logger.error(f"Failed to save cookies: {str(e)}")
            raise
    
    async def load_cookies(self, context: BrowserContext, profile_name: str) -> bool:
        """
        Load saved cookies into context
        """
        try:
            profile = self.saved_profiles.get(profile_name)
            if not profile:
                return False
            
            await context.add_cookies(profile.cookies)
            return True
            
        except Exception as e:
            logger.error(f"Failed to load cookies: {str(e)}")
            return False
    
    async def handle_two_factor_auth(self, page: Page, tfa_selector: Optional[str] = None) -> bool:
        """
        Handle two-factor authentication (requires manual intervention)
        """
        try:
            if not tfa_selector:
                # Look for common 2FA input patterns
                tfa_selectors = [
                    'input[name="code"]',
                    'input[name="otp"]',
                    'input[name="2fa"]',
                    'input[placeholder*="code"]',
                    'input[placeholder*="verification"]'
                ]
                
                for selector in tfa_selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element:
                            tfa_selector = selector
                            break
                    except:
                        continue
            
            if not tfa_selector:
                return False  # No 2FA detected
            
            # Wait for manual 2FA input (30 seconds timeout)
            logger.info("Waiting for 2FA code input...")
            
            # You could implement a webhook or other mechanism to get the 2FA code
            # For now, we'll wait for the user to manually input it
            
            # Wait for form submission or navigation
            await page.wait_for_load_state('networkidle', timeout=30000)
            
            return True
            
        except Exception as e:
            logger.error(f"2FA handling failed: {str(e)}")
            return False
    
    async def handle_captcha(self, page: Page) -> bool:
        """
        Handle CAPTCHA challenges (requires manual intervention or external service)
        """
        try:
            # Look for common CAPTCHA indicators
            captcha_selectors = [
                '.captcha',
                '#captcha',
                'iframe[src*="recaptcha"]',
                'iframe[src*="captcha"]',
                '[class*="captcha"]'
            ]
            
            captcha_found = False
            for selector in captcha_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        captcha_found = True
                        break
                except:
                    continue
            
            if not captcha_found:
                return True  # No CAPTCHA detected
            
            logger.warning("CAPTCHA detected - manual intervention required")
            
            # You could integrate with CAPTCHA solving services here
            # For now, we'll wait for manual resolution
            
            # Wait for CAPTCHA resolution (60 seconds timeout)
            await asyncio.sleep(60)
            
            return True
            
        except Exception as e:
            logger.error(f"CAPTCHA handling failed: {str(e)}")
            return False
    
    def create_login_config(self, site_config: Dict[str, Any]) -> LoginCredentials:
        """
        Create login credentials from configuration
        """
        return LoginCredentials(
            username=site_config['username'],
            password=site_config['password'],
            login_url=site_config['login_url'],
            username_selector=site_config['username_selector'],
            password_selector=site_config['password_selector'],
            submit_selector=site_config['submit_selector'],
            success_indicator=site_config.get('success_indicator'),
            additional_fields=site_config.get('additional_fields', {})
        )
    
    async def test_login(self, credentials: LoginCredentials) -> Dict[str, Any]:
        """
        Test login credentials without saving session
        """
        from playwright.async_api import async_playwright
        
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            success = await self.login(page, credentials)
            
            result = {
                'success': success,
                'final_url': page.url,
                'cookies_count': len(await context.cookies()) if success else 0
            }
            
            if success:
                # Get page title to verify successful login
                title = await page.title()
                result['page_title'] = title
            
            return result
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

# Predefined login configurations for popular sites
PREDEFINED_LOGINS = {
    'linkedin': {
        'login_url': 'https://www.linkedin.com/login',
        'username_selector': '#username',
        'password_selector': '#password',
        'submit_selector': 'button[type="submit"]',
        'success_indicator': '.feed-identity-module'
    },
    'facebook': {
        'login_url': 'https://www.facebook.com/login',
        'username_selector': '#email',
        'password_selector': '#pass',
        'submit_selector': 'button[name="login"]',
        'success_indicator': '[role="banner"]'
    },
    'twitter': {
        'login_url': 'https://twitter.com/login',
        'username_selector': 'input[name="text"]',
        'password_selector': 'input[name="password"]',
        'submit_selector': '[data-testid="LoginForm_Login_Button"]',
        'success_indicator': '[data-testid="SideNav_AccountSwitcher_Button"]'
    },
    'instagram': {
        'login_url': 'https://www.instagram.com/accounts/login/',
        'username_selector': 'input[name="username"]',
        'password_selector': 'input[name="password"]',
        'submit_selector': 'button[type="submit"]',
        'success_indicator': '[aria-label="Home"]'
    }
}
