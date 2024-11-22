import os
import re
import uuid
import pandas as pd
import openpyxl
from urllib.parse import urlparse, parse_qs
from flask import Flask, render_template, request, make_response, redirect, jsonify, session, url_for, flash, abort
import stripe

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

# Load the Excel file once
EXCEL_FILE = 'products.xlsx'
products_df = pd.read_excel(EXCEL_FILE)

stripe.api_key = 'sk_test_51QBHQYGVTn4SmrQAGiIq94dGA1TLbVF8TXo1ZB2An4vaxVYHB1otKw5k9sbonM4PHQfrKYITRzvWRX4fX0SXeJTt00t34RO3Cb'


@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        # Get cart items from session
        cart = session.get('cart', [])

        # Create line items dynamically from the cart
        line_items = []
        for item in cart:
            line_items.append({
                'price_data': {
                    'currency': 'gbp',
                    'product_data': {
                        'name': item['Name'],
                    },
                    'unit_amount': int(item['Price'] * 100),  # Stripe expects amount in cents
                },
                'quantity': item['Quantity'],
            })

        # Create a new Checkout Session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=url_for('checkout_success', _external=True),  # Ensure this URL is absolute
            cancel_url=url_for('MyCart', _external=True),  # Redirect back to the cart if payment fails
        )

        return jsonify({
            'sessionId': checkout_session.id
        })
    except Exception as e:
        return jsonify(error=str(e)), 403


# Step 3: Add HTTPS redirection before any request is processed
@app.before_request
def https_redirect():
    if not request.is_secure and request.headers.get('x-forwarded-proto') != 'https':
        # Redirect HTTP requests to HTTPS
        return redirect(request.url.replace('http://', 'https://', 1), code=301)


@app.before_request
def initialize_cart():
    if 'cart' not in session:
        session['cart'] = []


@app.context_processor
def inject_cart():
    # Pass the cart and its length to all templates
    cart = session.get('cart', [])
    return dict(cart_length=len(cart))  # Inject cart length into the context


@app.route('/checkout-success')
def checkout_success():
    # Display success message or store transaction details
    return render_template('index.html')


@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    product = request.get_json()  # Get the product data from the request
    product_id = int(product['ID'])

    # Initialize the cart in session if it doesn't exist
    if 'cart' not in session:
        session['cart'] = []

    # Check if the product already exists in the cart
    cart = session['cart']
    existing_item = next((item for item in cart if item['ID'] == product_id), None)

    if existing_item:
        # If product already in cart, increase the quantity
        existing_item['Quantity'] += 1
    else:
        # Add the new product to the cart with quantity 1
        product['Quantity'] = 1
        product['Price'] = float(product['Price'])
        cart.append(product)

    # Save the updated cart to the session
    session['cart'] = cart

    # Return the updated cart length and items to update the frontend
    return jsonify({
        'cart_length': len(cart),
        'cart_items': cart  # Sending back the entire cart to update the UI
    })


@app.template_filter('sum')
def sum_filter(cart, attribute, attr=None):
    if attr:
        return sum(float(item[attribute]) * int(item[attr]) for item in cart)
    return sum(float(item[attribute]) for item in cart)


@app.after_request
def add_response_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = "0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.route('/product/<int:product_id>')
def product_page(product_id):
    # Fetch the row matching the product_id
    product_row = products_df.iloc[product_id - 1]  # Adjust for 0-indexing
    product = {
        'ID': product_id,
        'Name': product_row['Name'],
        'Price': product_row['Price'],
        'Description': product_row['Description'],
        'ImageURLs': product_row['ImageURLs'],
        # 'Features': product_row['Features'].split('\n')  # Assume features are newline-separated
        'Stock': product_row['Stock'],
    }
    return render_template('productPage.html', product=product)


@app.route('/PetrolPowered')
def PetrolPowered():
    return render_template('PetrolPowered.html')


@app.route('/DieselPowered')
def DieselPowered():
    return render_template('DieselPowered.html')


@app.route('/ElectricPowered')
def ElectricPowered():
    return render_template('ElectricPowered.html')


@app.route('/MyCart')
def MyCart():
    cart = session.get('cart', [])
    subtotal = sum(item['Price'] * item['Quantity'] for item in cart)
    return render_template('MyCart.html', cart=cart, subtotal=subtotal)


@app.route("/", methods=['GET'])
def hello_world():
    response = make_response(render_template('index.html'))
    return response


if __name__ == "__main__":
    app.run(debug=False)


