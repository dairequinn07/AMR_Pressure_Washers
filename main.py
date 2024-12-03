import os
from datetime import timedelta
import pandas as pd
import requests
from flask import Flask, render_template, request, make_response, redirect, jsonify, session, url_for, flash, abort
from square.client import Client
from square.http.auth.o_auth_2 import BearerAuthCredentials

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Load the Excel file once
EXCEL_FILE = 'products.xlsx'
products_df = pd.read_excel(EXCEL_FILE)


client = Client(bearer_auth_credentials=BearerAuthCredentials(access_token=os.environ['SQUARE_ACCESS_TOKEN_PROD']),
                environment='production')

# client = Client(bearer_auth_credentials=BearerAuthCredentials(access_token=os.environ['SQUARE_ACCESS_TOKEN']),
#                 environment='sandbox')


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


@app.after_request
def add_response_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = "0"
    response.headers["Pragma"] = "no-cache"
    return response


# Replace with a function to fetch location_id dynamically
def fetch_location_id(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = "https://connect.squareup.com/v2/locations"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        locations = response.json().get("locations", [])
        if locations:
            print("Fetched Location ID:", locations[0]["id"])
            return locations[0]["id"]  # Use the first location ID
        else:
            print("No locations found.")
    else:
        print("Error fetching location ID:", response.json())
    return None


# Function to create a payment link dynamically
def create_payment_link():
    location_id = os.environ.get('LOCATION_ID')
    data = request.get_json()
    delivery_option = data.get('deliveryOption', 'pickup')  # Default to 'pickup' if not provided
    pickup_address = '21 Annaghmore Rd, Cookstown BT80 0JQ'

    # Get cart items from session
    cart = session.get('cart', [])

    # Create line items dynamically from the cart
    line_items = [
        {
            'name': item['Name'],
            'quantity': str(item['Quantity']),
            'base_price_money': {
                'amount': 0,
                'currency': 'GBP',
            }
        }
        for item in cart
    ]

    # Add delivery fee if applicable
    if delivery_option == 'delivery':
        line_items.append({
            'name': 'Delivery Fee',
            'quantity': '1',
            'base_price_money': {
                'amount': 3000,
                'currency': 'GBP',
            }
        })

    # Build the order body
    order_body = {
        "location_id": location_id,
        "line_items": line_items,
    }

    # Add metadata and shipping options
    metadata = {"delivery_option": delivery_option}
    if delivery_option == 'pickup':
        metadata["pickup_address"] = pickup_address
    order_body["metadata"] = metadata

    # Set checkout options
    checkout_options = {
        "redirect_url": url_for('checkout_success', _external=True),
        "ask_for_shipping_address": (delivery_option == 'delivery'),
    }

    # Generate the payment link
    response = client.checkout.create_payment_link(
        body={
            "order": order_body,
            "checkout_options": checkout_options,
        }
    )

    # Handle the API response
    if response.is_success():
        return response.body['payment_link']  # Return the payment link
    else:
        # Improved error logging
        print(f"Error creating payment link: {response.errors}")
        return None


@app.route("/squareAuthorization", methods=['GET'])
def squareAuthorization():
    # Get the authorization code from the query parameters
    authorization_code = request.args.get('code')

    if not authorization_code:
        return "Authorization code missing", 400

    client_id = os.environ.get("SQUARE_APPLICATION_ID")
    client_secret = os.environ.get("SQUARE_SECRET")
    redirect_uri = "https://amrpressurewashers-37d8c0c7dd80.herokuapp.com/squareAuthorization"

    # Token exchange request
    url = "https://connect.squareup.com/oauth2/token"
    headers = {"Content-Type": "application/json"}
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": authorization_code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        token_info = response.json()
        access_token = token_info.get('access_token')
        merchant_id = token_info.get('merchant_id')
        expires_in = token_info.get('expires_in')  # Get the expiration time in seconds

        # Fetch the location_id
        location_id = fetch_location_id(access_token)  # Pass the access_token dynamically
        if location_id:
            print("Location ID:", location_id)
        else:
            print("Failed to fetch Location ID.")

        # Return a response with details displayed to the user
        return make_response(render_template('squareAuthorization.html',
                                             access_token=access_token,
                                             merchant_id=merchant_id,
                                             location_id=location_id,
                                             expires_in=expires_in))
    else:
        print("Error exchanging authorization code:", response.json())
        return "Error during authorization code exchange", 500


@app.route('/create-checkout-link', methods=['POST'])
def generate_checkout():
    payment_link = create_payment_link()
    if payment_link:
        return jsonify({'payment_link': payment_link['url']}), 200
    else:
        return jsonify({'error': 'Unable to generate payment link'}), 500


@app.route('/checkout-success', methods=['GET'])
def checkout_success():
    # Example session data
    cart = session.get('cart', [])
    delivery_option = session.get('deliveryOption', 'pickup')
    total_amount = session.get('totalAmount', 0)  # Total including delivery if applicable

    return render_template(
        'payment_summary.html',
        cart=cart,
        delivery_option=delivery_option,
        total_amount=total_amount
    )


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
    products = products_df[products_df['Department'] == 'Petrol Washer'].to_dict(orient='records')
    return render_template('petrolWashers.html', products=products)


@app.route('/DieselPowered')
def DieselPowered():
    products = products_df[products_df['Department'] == 'Diesel Washer'].to_dict(orient='records')
    return render_template('dieselWashers.html', products=products)


@app.route('/ElectricPowered')
def ElectricPowered():
    products = products_df[products_df['Department'] == 'Electric Washer'].to_dict(orient='records')
    return render_template('electricWashers.html', products=products)


@app.route('/PTOPowered')
def PTOPowered():
    products = products_df[products_df['Department'] == 'PTO Washer'].to_dict(orient='records')
    return render_template('ptoWashers.html', products=products)


@app.route('/Generators')
def Generators():
    products = products_df[products_df['Department'] == 'Generator'].to_dict(orient='records')
    return render_template('generators.html', products=products)


@app.route('/Parts')
def Parts():
    products = products_df[products_df['Department'] == 'Parts'].to_dict(orient='records')
    return render_template('parts.html', products=products)


@app.route('/MyCart')
def MyCart():
    cart = session.get('cart', [])
    subtotal = sum(item['Price'] * item['Quantity'] for item in cart)
    return render_template('myCart.html', cart=cart, subtotal=subtotal)


@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    data = request.get_json()
    item_id = int(data.get('id'))  # Get the item ID from the request

    if 'cart' in session:
        session['cart'] = [item for item in session['cart'] if int(item['ID']) != int(item_id)]
        session.modified = True  # Mark the session as modified

        return jsonify({
            "success": True,
            "message": "Item removed from cart",
            "cart_length": len(session['cart']),
            "cart_items": session['cart']
        })

    return jsonify({"success": False, "message": "Cart not found"}), 404


@app.context_processor
def inject_cart():
    # Pass the cart and its length to all templates
    cart = session.get('cart', [])
    return dict(cart_length=len(cart))  # Inject cart length into the context


@app.route("/", methods=['GET'])
def hello_world():
    session.permanent = True
    response = make_response(render_template('index.html'))
    return response


if __name__ == "__main__":
    app.run(debug=False)


