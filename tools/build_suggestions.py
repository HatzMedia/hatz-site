#!/usr/bin/env python3
"""
One-time helper: turns a first-pass reading of the video titles into review suggestions.

It writes data/suggestions.json. Nothing here goes on the map by itself. The /review/ page shows each
suggestion, and Hatz confirms it, fixes the pin, or leaves it out.

Pins come from OpenStreetMap's free search (Nominatim, one request per second). Small businesses are
often missing there, so some suggestions come back without a pin and the review page asks for an address.

    python tools/build_suggestions.py            look up pins for every suggested place
    python tools/build_suggestions.py --no-geocode   skip the lookups
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "HatzSiteBuilder/1.0 (Hatz@hatzmedia.com)"}
CINCY_VIEWBOX = "-85.3,38.6,-83.6,39.7"  # west,south,east,north: leans results toward the Cincinnati area

# key: (display name, area label, search text, type, road trip?, [video ids])
SPEC = {
    "webn-fireworks": ("WEBN Fireworks", "Downtown Cincinnati, OH", "Smale Riverfront Park, Cincinnati, OH", "events", False, ["0WNlHhwWBN0", "4abF0_bYLNE"]),
    "tickled-sweet": ("Tickled Sweet & Harvest Market", "Milford, OH", "Tickled Sweet, Milford, OH", "sweets", False, ["Gt-2LY3WIPo"]),
    "st-bernadette": ("St. Bernadette Festival", "Amelia, OH", "St. Bernadette Church, Amelia, OH", "events", False, ["g-a1JcM9iV8", "mARaaWNKags"]),
    "ollies-trolley": ("Ollie's Trolley", "Cincinnati, OH", "Ollie's Trolley, Cincinnati, OH", "eats", False, ["C6WBYeLjvuE"]),
    "mt-washington-creamy-whip": ("Mount Washington Creamy Whip", "Mount Washington, Cincinnati, OH", "Mount Washington Creamy Whip, Cincinnati, OH", "sweets", False, ["p-nqIY34LY8"]),
    "shaw-farms": ("Shaw Farms", "Milford, OH", "Shaw Farms, Milford, OH", "shopping", False, ["YBOvxYg7Jzw"]),
    "great-inland-seafood-festival": ("Great Inland Seafood Festival", "Cincinnati, OH", "Great Inland Seafood Festival, Cincinnati, OH", "events", False, ["PXetsaQn0L4"]),
    "kungfood-amerasia": ("KungFood Amerasia", "Covington, KY", "KungFood Amerasia, Covington, KY", "eats", False, ["gS3y1LWECQk"]),
    "uncle-johns-place": ("Uncle John's Place", "Mansfield, OH", "Uncle John's Place, Mansfield, OH", "eats", True, ["cScpuxP_PkE"]),
    "mercer-social-house": ("Mercer Social House", "Newtown, OH", "Mercer Social House, Newtown, OH", "eats", False, ["IfGTYoYhEeA"]),
    "kewpee-hamburgers-lima": ("Kewpee Hamburgers", "Lima, OH", "Kewpee Hamburgers, Lima, OH", "eats", True, ["vRTYB7fxRTU"]),
    "corner-dumpling-house": ("Corner Dumpling House", "Cincinnati, OH", "Corner Dumpling House, Cincinnati, OH", "eats", False, ["xix1nHl7JhU", "VVIXvopiqAg", "E6Efp0f2LOA"]),
    "sweets-and-geeks": ("Sweets & Geeks", "Sandusky, OH", "Sweets & Geeks, Sandusky Mall, Sandusky, OH", "sweets", True, ["INA5zVtnzRg"]),
    "local-producers-collective": ("Local Producers Collective", "Cincinnati, OH", "Local Producers Collective, Cincinnati, OH", "shopping", False, ["0ApVfs4hhyc", "_doFOmcnpVY", "q86ozI9ciiA"]),
    "st-veronica-festival": ("St. Veronica Festival", "Cincinnati, OH", "St. Veronica Church, Cincinnati, OH", "events", False, ["VE7j8O90TYU"]),
    "old-dutch-tavern": ("Old Dutch Tavern", "Sandusky, OH", "Old Dutch Tavern, Sandusky, OH", "eats", True, ["PdZtZJM1uGo"]),
    "basil-1791": ("Basil 1791", "Cincinnati, OH", "Basil 1791, Cincinnati, OH", "eats", False, ["OfWBWIKw2eE"]),
    "diegos-tacos": ("Diego's Tacos", "Batavia, OH", "Diego's Tacos, Batavia, OH", "eats", False, ["L2-q4ku0-l4", "tqHG42feslA"]),
    "the-roost": ("The Roost", "Latonia, KY", "The Roost, Latonia, KY", "shopping", False, ["nkIZkj4zh9g"]),
    "sandusky-pancake-house": ("Sandusky Pancake House", "Sandusky, OH", "Sandusky Pancake House, Sandusky, OH", "eats", True, ["ApQBviUosn4"]),
    "heineman-winery": ("Heineman Winery & Crystal Cave", "Put-in-Bay, OH", "Heineman Winery, Put-in-Bay, OH", "family", True, ["r7-jBjDA1R0"]),
    "fruit-land-newport": ("Fruit Land", "Newport, KY", "Fruitland, Newport, KY", "shopping", False, ["qyHe5SKzs44", "q6CdTI7bUrc"]),
    "newtown-farm-market": ("Newtown Farm Market", "Newtown, OH", "Newtown Farm Market, Newtown, OH", "shopping", False, ["KYCIw4iOXdg", "RcxbmcQbAZ4"]),
    "takumi-sushi-hibachi": ("Takumi Sushi & Hibachi", "Mason, OH", "Takumi Sushi & Hibachi, Mason, OH", "eats", False, ["fWmd9B0Ae_s"]),
    "paradise-ice": ("Paradise Ice", "Milford, OH", "Paradise Ice, Milford, OH", "sweets", False, ["L4pESLGcn7M", "1UkTHOyh77Q"]),
    "the-invention-restaurant": ("The Invention Restaurant", "Milan, OH", "The Invention Restaurant, Milan, OH", "eats", True, ["WTwShAVeZuU"]),
    "milkshake-factory": ("MilkShake Factory", "Cincinnati area, OH", "MilkShake Factory, Cincinnati, OH", "sweets", False, ["WJTzv407vQc"]),
    "cincy-gourmet-deli": ("Cincy Gourmet Deli", "Cincinnati, OH", "Cincy Gourmet Deli, Cincinnati, OH", "eats", False, ["p3nDO2B6hD0"]),
    "element-eatery": ("Element Eatery", "Cincinnati area, OH", "Element Eatery, Cincinnati, OH", "eats", False, ["q1GVfhIImKM"]),
    "big-daddys-amelia": ("Big Daddy's", "Amelia, OH", "Big Daddy's, Amelia, OH", "eats", False, ["EtEDalNHr24"]),
    "traders-world": ("Traders World Flea Market", "Monroe, OH", "Traders World, Monroe, OH", "shopping", False, ["mioV3f9yahc", "S7LFJbXykGw", "WD-B2E7UZFI"]),
    "padrino-milford": ("Padrino", "Milford, OH", "Padrino, Milford, OH", "eats", False, ["IVzaDcqNzSU"]),
    "legendary-whip": ("Legendary Whip", "Ohio", "Legendary Whip, Ohio", "eats", False, ["047sXWdO1Yg"]),
    "house-of-plastik": ("House of Plastik", "Cincinnati, OH", "House of Plastik, Cincinnati, OH", "shopping", False, ["w5FOWXvpTZQ"]),
    "seoul-korean-bbq": ("Seoul Korean BBQ & Hot Pot", "Cincinnati area, OH", "Seoul Korean BBQ & Hot Pot, Cincinnati, OH", "eats", False, ["JvTlWifMKK0", "9sQvRQ95__Q"]),
    "blue-ash-chili": ("Blue Ash Chili", "Blue Ash, OH", "Blue Ash Chili, Blue Ash, OH", "eats", False, ["_RcO18zraI8"]),
    "cincinnati-union-terminal": ("Cincinnati Union Terminal", "Cincinnati, OH", "Cincinnati Union Terminal, Cincinnati, OH", "family", False, ["JWNr0BSteIA", "-6bgSZsxYpo", "ft2v-_8NknY"]),
    "bells-grab-and-go": ("Bell's Grab & Go", "Mount Healthy, OH", "Bell's Grab & Go, Mount Healthy, OH", "eats", False, ["-Mlq0mfiGXI"]),
    "sugar-n-spice": ("Sugar n' Spice", "Cincinnati, OH", "Sugar n' Spice Restaurant, Cincinnati, OH", "eats", False, ["AI_vpMO0R_Q"]),
    "goshen-grind": ("Goshen Grind", "Goshen, OH", "Goshen Grind, Goshen, OH", "eats", False, ["l0bTwb5XVzE"]),
    "tokugawa": ("Tokugawa", "Cincinnati area, OH", "Tokugawa Hibachi, Cincinnati, OH", "eats", False, ["HMZg2jS2dFY"]),
    "northside-yacht-club": ("Northside Yacht Club", "Northside, Cincinnati, OH", "Northside Yacht Club, Cincinnati, OH", "eats", False, ["j-cKDONquCA"]),
    "layla-mediterranean": ("Layla Mediterranean", "Cincinnati area, OH", "Layla Mediterranean, Cincinnati, OH", "eats", False, ["ohZLZ5qQduk"]),
    "fountain-square": ("Fountain Square", "Downtown Cincinnati, OH", "Fountain Square, Cincinnati, OH", "events", False, ["LItUuvlHE84"]),
    "east-fork-lake": ("East Fork State Park", "Bethel, OH", "East Fork State Park, Bethel, OH", "family", False, ["mo0IOMzAvU8"]),
    "cincinnati-christkindlmarkt": ("Cincinnati Christkindlmarkt", "Cincinnati, OH", "Cincinnati Christkindlmarkt, Cincinnati, OH", "events", False, ["FPTFJEGnriA"]),
    "yuletide-village": ("Yuletide Village", "Cincinnati area, OH", "Yuletide Village, Cincinnati, OH", "events", False, ["sPQV8Wbj54I", "LDki79ph3gA", "YKAeiyCH6qA", "wehGtYbGdek"]),
    "corsi-tree-farm": ("Corsi Tree Farm", "Ohio", "Corsi Tree Farm, Ohio", "family", False, ["26u1jeZq_PU", "a4O-s8_Wi_0"]),
    "loris-grill": ("Lori's Grill", "Goshen, OH", "Lori's Grill, Goshen, OH", "eats", False, ["XxP6k4M38K0"]),
    "masa-gyro": ("Masa Gyro", "Cincinnati area, OH", "Masa Gyro, Cincinnati, OH", "eats", False, ["dM8hZWTSD3w"]),
    "grant-garden-center": ("Grant Garden Center", "Ohio", "Grant Garden Center, Ohio", "shopping", False, ["qHjiu5kQGRQ"]),
    "el-coyote": ("El Coyote", "Anderson Township, OH", "El Coyote, Anderson Township, OH", "eats", False, ["jccpj-7Swx8"]),
    "the-porch": ("The Porch", "Cincinnati area, OH", "The Porch, Cincinnati, OH", "eats", False, ["q8Xro7lpl5I"]),
    "buttermilks-bakery": ("ButterMilk's Bakery", "Hillsboro, OH", "ButterMilk's Bakery, Hillsboro, OH", "sweets", False, ["e4xc1nCP33g"]),
    "mi-cozumel": ("Mi Cozumel", "Cincinnati area, OH", "Mi Cozumel, Cincinnati, OH", "eats", False, ["XgKHKX65Cj4"]),
    "the-arepa-place": ("The Arepa Place", "Cincinnati area, OH", "The Arepa Place, Cincinnati, OH", "eats", False, ["bf4r93UGKOg"]),
    "birdies-coffee": ("Birdie's Coffee Co.", "Norwood, OH", "Birdie's Coffee Co, Norwood, OH", "eats", False, ["KlqAbxlHOIw"]),
    "la-michoacana": ("La Michoacana Y Sus Antojitos", "Cincinnati, OH", "La Michoacana Y Sus Antojitos, Cincinnati, OH", "sweets", False, ["SWuI8kyYwqM"]),
    "swampwater-grill": ("SwampWater Grill", "Ohio", "SwampWater Grill, Ohio", "eats", False, ["zpG0KNrsmBs"]),
    "parlor-doughnuts": ("Parlor Doughnuts", "Anderson Township, OH", "Parlor Doughnuts, Anderson Township, OH", "sweets", False, ["OaNzhf3-w_E"]),
    "country-inn-withamsville": ("Country Inn Withamsville", "Withamsville, OH", "Country Inn, Withamsville, OH", "eats", False, ["k8KQLcNNXM0"]),
    "circuit-cafe": ("Circuit Café", "Cincinnati area, OH", "Circuit Cafe, Cincinnati, OH", "eats", False, ["fRY-VT9MM-Q"]),
    "mocha-and-co": ("Mocha & Co.", "West Chester, OH", "Mocha & Co, West Chester, OH", "sweets", False, ["2nb0edvim9o"]),
    "fairborn-halloween": ("Fairborn Halloween Festival", "Fairborn, OH", "Fairborn, OH", "events", True, ["pO69z8AhHg4", "J1SYtXL7PMU", "Bcs6PBh_oxk"]),
    "the-food-pitt": ("The Food Pitt", "Ohio", "The Food Pitt, Ohio", "eats", False, ["2OWrjLD94_c"]),
    "feel-good-food-stop": ("Feel Good Food Stop", "Newtown, OH", "Feel Good Food Stop, Newtown, OH", "eats", False, ["5fIxG3RAtZA"]),
    "doschers-candies": ("Doscher's Candies", "Newtown, OH", "Doscher's Candies, Newtown, OH", "sweets", False, ["ZYSZRhVGLyc"]),
    "newport-aquarium": ("Newport Aquarium", "Newport, KY", "Newport Aquarium, Newport, KY", "family", False, ["Ww0kIGQylTA", "7IeMpHDO72M"]),
    "waffle-house-amelia": ("Waffle House", "Amelia, OH", "Waffle House, Amelia, OH", "eats", False, ["d-W1eCTJm30"]),
    "village-coffee-shop": ("Village Coffee Shop", "Newtown, OH", "Village Coffee Shop, Newtown, OH", "eats", False, ["PboDUQWG-SM"]),
    "pumpkin-run-nationals": ("Pumpkin Run Nationals", "Owensville, OH", "Owensville, OH", "events", False, ["rLVN1GDqgyg"]),
    "pepper-pod": ("Pepper Pod", "Cincinnati area, OH", "Pepper Pod, Cincinnati, OH", "eats", False, ["7dQ3xmej_zw"]),
    "roneys": ("Roney's", "Ohio", "Roney's Restaurant, Ohio", "eats", False, ["wUoajMSfVew"]),
    "bards-burgers-and-chili": ("Bard's Burgers & Chili", "Latonia, KY", "Bard's Burgers & Chili, Latonia, KY", "eats", False, ["MiQgvNamNRM"]),
    "pig-candy-bbq": ("Pig Candy BBQ", "Cincinnati, OH", "Pig Candy BBQ, Kellogg Ave, Cincinnati, OH", "eats", False, ["zpjnmZOukbE"]),
    "peters-cartridge-factory": ("Peters Cartridge Factory", "Maineville, OH", "Peters Cartridge Factory, Maineville, OH", "eats", False, ["Z6mJQNFHaa8"]),
    "kroger-wellness-festival": ("Kroger Wellness Festival", "Cincinnati, OH", "Cincinnati, OH", "events", False, ["BKGWYmUlRYw"]),
    "lazlos-iron-skillet": ("Lazlo's Iron Skillet", "Ohio", "Lazlo's Iron Skillet, Ohio", "eats", False, ["sVeQVqBwhlE"]),
    "liberty-collective": ("Liberty Collective", "Liberty Township, OH", "Liberty Collective, Liberty Township, OH", "eats", False, ["pbML3MMRDi0"]),
    "graeters-anderson": ("Graeter's", "Anderson Township, OH", "Graeter's, Anderson Township, OH", "sweets", False, ["T_Di2H9UZ_k"]),
    "cincinnati-fear-fest": ("Cincinnati Fear Fest", "Cincinnati, OH", "Cincinnati Fear Fest, Cincinnati, OH", "events", False, ["swVspYaMth4"]),
    "kennys-place": ("Kenny's Place", "Ohio", "Kenny's Place, Ohio", "eats", False, ["kWlwLOZ1qaI"]),
    "the-chill-out": ("The Chill Out", "Ohio", "The Chill Out, Ohio", "eats", False, ["l5Y_eGnPaCE"]),
    "mr-hayeks": ("Mr. Hayek's", "Ohio", "Mr. Hayek's, Ohio", "eats", False, ["zOu-wg4e0x4"]),
    "yummy-bowl": ("Yummy Bowl", "Ohio", "Yummy Bowl, Ohio", "eats", False, ["4KGk9PRD6yw"]),
    "clermont-county-fair": ("Clermont County Fair", "Owensville, OH", "Clermont County Fairgrounds, Owensville, OH", "events", False, ["Osju-Q_aSzk"]),
    "vinny-rays-bbq": ("Vinny Ray's BBQ", "Felicity, OH", "Felicity, OH", "eats", False, ["cIPn2_CzueY"]),
    "rise-and-dine": ("Rise & Dine Breakfast", "Bethel, OH", "Rise & Dine, Bethel, OH", "eats", False, ["PmMPaBOKDs4"]),
    # found by reading the video descriptions
    "mr-smiths-coffee-house": ("Mr. Smith's Coffee House", "Sandusky, OH", "Mr. Smith's Coffee House, Sandusky, OH", "eats", True, ["lMaY0adZmnA"]),
    "corner-inn-upper-sandusky": ("Corner Inn Restaurant", "Upper Sandusky, OH", "Corner Inn Restaurant, Upper Sandusky, OH", "eats", True, ["RNr59XTM6zE"]),
    "village-pump": ("The Village Pump", "Kelleys Island, OH", "The Village Pump, Kelleys Island, OH", "eats", True, ["VGwRm1fdnvo"]),
    "uncle-beths-bbq": ("Uncle Beth's BBQ", "Ohio", "Uncle Beth's BBQ, Ohio", "eats", True, ["tT9A09OAy58"]),
    "tokyo-grill": ("Tokyo Grill Sushi & Hibachi Buffet", "Mason, OH", "Tokyo Grill, Mason, OH", "eats", False, ["QfM8_aBCr18"]),
    "cm-chicken": ("CM Chicken", "Cincinnati area, OH", "CM Chicken, Cincinnati, OH", "eats", False, ["8KiA0aQmIZE"]),
    "friendship-kitchen": ("Friendship Kitchen", "Ohio", "Friendship Kitchen, Ohio", "eats", False, ["hJ1Toe34pVc"]),
    "plane-street-cafe": ("Plane Street Cafe", "Cincinnati area, OH", "Plane Street Cafe, Cincinnati, OH", "shopping", False, ["Ey7HTC8ztyM"]),
    "jeffs-candy-shop": ("Jeff's Candy Shop", "Cleveland, OH", "Jeff's Candy Shop, Cleveland, OH", "sweets", True, ["qmQeVs_I1Jw"]),
    "u-ni-rice": ("U Ni Rice", "Clifton, Cincinnati, OH", "U Ni Rice, Cincinnati, OH", "eats", False, ["bz3KLgCLv8E"]),
    "silver-spring-house": ("Silver Spring House", "Cincinnati, OH", "Silver Spring House, Cincinnati, OH", "eats", False, ["Q6XEMxIHEhc"]),
    "jukebox-mason": ("Jukebox", "Mason, OH", "Jukebox, Mason, OH", "sweets", False, ["p82t7LJSyAQ"]),
    "bourbon-house-pizza": ("Bourbon House Pizza", "Newport, KY", "Bourbon House Pizza, Newport, KY", "eats", False, ["bEOt2oqPefg"]),
    "bailey-jaynes": ("Bailey Jaynes", "Cincinnati area, OH", "Bailey Jaynes, Cincinnati, OH", "sweets", False, ["mlXyeHeyMrs"]),
}

# Street addresses confirmed by web search (Sept 29, 2026). A place with an address gets an exact pin.
# Value is (address, corrected display name or None, corrected area or None).
ADDRESSES = {
    "webn-fireworks": ("705 E Pete Rose Way, Cincinnati, OH 45202", "WEBN Fireworks at Sawyer Point", "Downtown Cincinnati, OH"),
    "st-bernadette": ("1479 Locust Lake Rd, Amelia, OH 45102", None, None),
    "mt-washington-creamy-whip": ("2069 Beechmont Ave, Cincinnati, OH 45230", "Mt. Washington Creamy Whip & Bakery", None),
    "shaw-farms": ("1737 State Route 131, Milford, OH 45150", None, None),
    "great-inland-seafood-festival": ("1 Levee Way, Newport, KY 41071", None, "Newport, KY"),
    "kungfood-amerasia": ("521 Madison Ave, Covington, KY 41011", "KungFood Chu's AmerAsia", None),
    "corner-dumpling-house": ("11371 Montgomery Rd, Cincinnati, OH 45249", None, "Symmes Township, OH"),
    "sweets-and-geeks": ("4314 Milan Rd, Sandusky, OH 44870", "Sweets & Geeks (Sandusky Mall)", None),
    "local-producers-collective": ("95 W Main St, Batavia, OH 45103", None, "Batavia, OH"),
    "st-veronica-festival": ("4473 Mt Carmel Tobasco Rd, Cincinnati, OH 45244", None, "Mt. Carmel, OH"),
    "old-dutch-tavern": ("2219 E Perkins Ave, Sandusky, OH 44870", None, None),
    "basil-1791": ("241 High St, Hamilton, OH 45011", None, "Hamilton, OH"),
    "diegos-tacos": ("1006 Old State Route 74, Batavia, OH 45103", "Diego's Street Tacos", None),
    "the-roost": ("3616 Decoursey Ave, Covington, KY 41015", "The Roost Latonia", None),
    "newtown-farm-market": ("3950 Round Bottom Rd, Cincinnati, OH 45244", None, None),
    "takumi-sushi-hibachi": ("12071 Mason Montgomery Rd, Cincinnati, OH 45249", "Takumi Steakhouse", None),
    "paradise-ice": ("1313 State Route 131, Milford, OH 45150", None, None),
    "milkshake-factory": ("2144 Kings Mills Rd, Mason, OH 45040", None, "Mason, OH"),
    "cincy-gourmet-deli": ("2832 Jefferson Ave, Cincinnati, OH 45219", None, "Clifton Heights, Cincinnati, OH"),
    "big-daddys-amelia": ("14 W Main St, Amelia, OH 45102", "Big Daddy Marketplace", None),
    "traders-world": ("601 Union Rd, Monroe, OH 45050", None, None),
    "legendary-whip": ("3376 State Route 125, Bethel, OH 45106", "Legen-Dairy Whip", "Bethel, OH"),
    "seoul-korean-bbq": ("5113 Bowen Dr, Mason, OH 45040", None, "Mason, OH"),
    "bells-grab-and-go": ("1355 Compton Rd, Cincinnati, OH 45231", None, None),
    "tokugawa": ("5723 Signal Hill Ct, Milford, OH 45150", "Tokugawa Japan Steakhouse", "Milford, OH"),
    "layla-mediterranean": ("7418 Beechmont Ave, Cincinnati, OH 45255", "Leyla Mediterranean", "Anderson Township, OH"),
    "east-fork-lake": ("3294 Elklick Rd, Bethel, OH 45106", None, None),
    "cincinnati-christkindlmarkt": ("115 Joe Nuxhall Way, Cincinnati, OH 45202", None, "The Banks, Cincinnati, OH"),
    "yuletide-village": ("10542 E State Route 73, Waynesville, OH 45068", None, "Waynesville, OH"),
    "loris-grill": ("1711 State Route 28, Goshen, OH 45122", "Lori's American Grille", None),
    "masa-gyro": ("1310 Ohio Pike, Amelia, OH 45102", None, "Amelia, OH"),
    "buttermilks-bakery": ("142 W Main St, Hillsboro, OH 45133", "ButterMilks Bakery", None),
    "la-michoacana": ("5225 Montgomery Rd, Cincinnati, OH 45212", None, "Norwood, OH"),
    "swampwater-grill": ("3742 Kellogg Ave, Cincinnati, OH 45226", "Swampwater Grill & Riverside Centre Antiques", "East End, Cincinnati, OH"),
    "mocha-and-co": ("7307 Tylers Corner Dr, West Chester, OH 45069", "Moka & Co.", None),
    "feel-good-food-stop": ("6836 Main St, Cincinnati, OH 45244", None, None),
    "doschers-candies": ("6926 Main St, Cincinnati, OH 45244", None, None),
    "pepper-pod": ("703 Monmouth St, Newport, KY 41071", "Pepper Pod Restaurant", "Newport, KY"),
    "lazlos-iron-skillet": ("1020 Ohio Pike, Cincinnati, OH 45245", "Laszlo's Iron Skillet", "Withamsville, OH"),
    "liberty-collective": ("6735 Lakota Ln, Liberty Township, OH 45044", None, None),
    "cincinnati-fear-fest": ("1449 Greenbush Cobb Rd, Williamsburg, OH 45176", None, "Williamsburg, OH"),
    "kennys-place": ("1340 State Route 125, Amelia, OH 45102", None, "Amelia, OH"),
    "the-chill-out": ("2792 Old State Route 32, Batavia, OH 45103", None, "Batavia, OH"),
    "mr-hayeks": ("11482 Springfield Pike, Cincinnati, OH 45246", "Mr. Hayek's Fish & Chicken", "Springdale, OH"),
    "vinny-rays-bbq": ("1295 State Route 756, Felicity, OH 45120", None, None),
    "rise-and-dine": ("101 E Plane St, Bethel, OH 45106", None, None),
    "mr-smiths-coffee-house": ("140 Columbus Ave, Sandusky, OH 44870", None, None),
    "corner-inn-upper-sandusky": ("143 N Sandusky Ave, Upper Sandusky, OH 43351", None, None),
    "uncle-beths-bbq": ("6262 State Route 245, North Lewisburg, OH 43060", None, "North Lewisburg, OH"),
    "tokyo-grill": ("5456 Kings Center Dr, Mason, OH 45040", None, None),
    "cm-chicken": ("7206 Towne Centre Dr, Liberty Township, OH 45069", None, "Liberty Township, OH"),
    "plane-street-cafe": ("125 W Plane St, Bethel, OH 45106", "The Plane Street Coffee House & Cafe", "Bethel, OH"),
    "jeffs-candy-shop": ("1238 Lost Nation Rd, Willoughby, OH 44094", None, "Willoughby, OH"),
    "u-ni-rice": ("2826 Short Vine St, Cincinnati, OH 45219", None, "Corryville, Cincinnati, OH"),
    "silver-spring-house": ("8322 E Kemper Rd, Cincinnati, OH 45249", None, "Symmes Township, OH"),
    "jukebox-mason": ("5859 Deerfield Blvd, Mason, OH 45040", None, None),
    "bailey-jaynes": ("5 N Main St, Walton, KY 41094", "Bailey Jaynes Bakery & Cafe", "Walton, KY"),
    "circuit-cafe": ("2726 Riverside Dr, Cincinnati, OH 45202", "Circuit Cafe / Cincinnati Cars & Coffee", "East End, Cincinnati, OH"),
    "pumpkin-run-nationals": ("1000 Locust St, Owensville, OH 45160", None, None),
    "clermont-county-fair": ("1000 Locust St, Owensville, OH 45160", None, None),
    "kroger-wellness-festival": ("5th St & Main St, Cincinnati, OH 45202", None, "Downtown Cincinnati, OH"),
    "fairborn-halloween": ("Main St & Central Ave, Fairborn, OH 45324", None, None),
    "grant-garden-center": ("Grant's Garden Center, Batavia, OH", "Grant's Garden Center Christmas Market", "Batavia, OH"),
}
# These two share a pin but are different events; keep them as two places so their pages read right.
# Places I could not pin down and left for Hatz: The Food Pitt (a Dayton food truck), Kroger Wellness Festival (a street festival).
UNSURE = {"the-food-pitt", "kroger-wellness-festival", "fairborn-halloween", "grant-garden-center", "cm-chicken", "lazlos-iron-skillet"}

# Videos that belong to a place that is already on the map
EXISTING = {"-eGqNc7zJe8": "eastgate-vendors-market", "TlcGOiHFFhQ": "kings-island"}

# Suggested "not a place video" (family, gaming, memes, chains with no single location)
SKIP_IDS = set("""09TyohpYewc -BkA4ujOE_4 fGw9HYVTEig 2IeTFgmZNOQ AB9DhL5W5Nw ZONHzTBTfCw 8e4teh_HB5Y Jrj-Xf45R9M 1HFISWqVtAs 1zxzXIwvsVA
QfNC3yWpFtw M_DiAe1GvXU DfMROlgenIw yQJI-oFajSM Lq2_v3ARr0s EMpQlW0sBiQ VDP646XPGHk UAtwFU82Lbc MtvhcZ54_Ag ZUJcIdWsvGI
l8hlZY4gHO0 GS8O75EA1Hw 4d0R4rdrHTw nksHsxLJHww rWqEHYwxhV8 QbWAcdbDj8Y UunHZij9orw aq1FcLip3bA 7a4W8cb_4u0 5jp8gJPiDN4 QK9bilMbqmo
G9hSS5VZ_cA gBXplfCAT6c LZ6G2DmDFgE JGCjsfvRkBE o-6kll1Gmes MQpjmkAZetA 1UrqFFvG1q8 FbqQKhzie28 1oesL1IyxMY TC_pmufOmZI R_NNl70H5RI
v2l2binW7p4 zKVGjpQWGno tqCLhWiTkTY clv1GMwcgMQ Mb8ZEdsMVUM vTyn2uau32w tuDoPiffw6w RjQRswot3bk cqJ-8pX2-iU FMBx1rvPc8s rLnsqzAG0jE
iiD2iqTd_J8 BZ-9Fd66vUs NAWoJcfiD6w FiCPri6fNmY tQB3ElzIw0M gdCuQxKqF4s Pv0FSyVX_kY O1BMc0EHNEs SDWFFTp9u7M sVn9utyR94k KtNGBpie7_U
LVCxb0_zh7Y O1wq4Yb8uL4 dekQRtJTjaU 84pPJ9kgvAU keq2151q9m0 VJz6ufpjTlI 65Wr6K6d4CI rU_FzChez-I mY8DZaJI-Zo aYq_BGua8SI 3ZHYN2vCrdo
MbRB1WP9MBM dO7QeEU_UD0 XwjRvvuBUzY 1mRTvozOauk voE-tw-TGAc GxpsaOq4jlM x7nlRjeIq94 J6bl7WnFTWs jdvw7aezrKQ 7eNWhevONgA SX5cmIQ_gNs
XOeJkIlxPFQ OeqcsTe1B1A 6snaTC3FSyU M2SFR_PkcUg q-2ZrFG_xjU VVyXKs_BJz0 EsVPQNtbE9w""".split())
# Keyword rules for the rest (gaming, Elf on the Shelf, Red Bull advent calendar)
SKIP_WORDS = ["redbull", "red bull", "advent calendar", "elfontheshelf", "arcraiders", "arc raiders", "raider", "warzone", "callofduty", "iracing", "nascar", "madden",
              "policesim", "trucksimulator", "lanoire", "baldur", "forza", "wrc", "proximity chat", "livetues", "live tues", "defib", "gamingclips"]


def geocode(query):
    p = {"format": "jsonv2", "limit": "3", "countrycodes": "us", "q": query}
    if "Cincinnati" in query or ", OH" in query or ", KY" in query:
        p.update(viewbox=CINCY_VIEWBOX, bounded="0")
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(p)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def squash(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main():
    videos = json.loads((ROOT / "data" / "videos.json").read_text(encoding="utf-8-sig"))
    pending = {v["id"]: v for v in videos if v["status"] == "pending"}
    do_geo = "--no-geocode" not in sys.argv

    places = []
    for key, (name, area, q, cat, trip, vids) in SPEC.items():
        vids = [v for v in vids if v in pending]
        if not vids:
            continue
        addr, fixed_name, fixed_area = ADDRESSES.get(key, ("", None, None))
        name, area = fixed_name or name, fixed_area or area
        rec = {"key": key, "name": name, "area": area, "cat": cat, "trip": trip, "videos": vids, "found": False,
               "address": addr, "weak": key in UNSURE}
        if do_geo:
            try:
                results, best = [], None
                if addr:
                    # a street address: take the top hit if it lands on the right street or town
                    street = squash(re.sub(r"^\d+\s*", "", addr.split(",")[0]))[:8]
                    town = squash(addr.split(",")[1] if "," in addr else "")
                    variants = [addr, addr.replace("State Route ", "OH-"), addr.replace("State Route ", "SR "),
                                re.sub(r"^\d+\s*", "", addr)]  # the map service is picky about road names
                    for attempt in variants:
                        results = geocode(attempt)
                        time.sleep(1.1)
                        best = next((r for r in results if street in squash(r.get("display_name", "")) or town in squash(r.get("display_name", ""))), None)
                        if best:
                            break
                    if best:
                        rec["precision"] = "exact" if re.match(r"^\d", addr) and best.get("addresstype") in ("building", "house", "amenity", "shop", "tourism", "leisure") or best.get("category") in ("amenity", "shop", "tourism", "leisure", "building") else "area"
                if not best:
                    token = squash(name)[:6]
                    for attempt in (q, name + " " + area, name.replace("&", "and") + " " + area.split(",")[0]):
                        results = geocode(attempt)
                        time.sleep(1.1)
                        best = next((r for r in results if token and token in squash(r.get("display_name", ""))), None)
                        if best:
                            rec["precision"] = "exact" if best.get("category") in ("amenity", "shop", "tourism", "leisure", "building", "historic") else "area"
                            break
                pick = best or (results[0] if results else None)
                if pick:
                    rec.update(found=True, lat=round(float(pick["lat"]), 5), lng=round(float(pick["lon"]), 5),
                               display=pick.get("display_name", ""), weak=rec["weak"] or best is None)
                    rec.setdefault("precision", "area")
            except Exception as e:
                rec["error"] = str(e)[:80]
            print("%-40s %s" % (name[:40], ("found " + rec.get("precision", "") + (" (check)" if rec.get("weak") else "")) if rec["found"] else "no pin"))
        places.append(rec)

    skips = []
    for vid, v in pending.items():
        text = (v["title"] + " " + v.get("desc", "")).lower()
        if vid in SKIP_IDS or any(w in text for w in SKIP_WORDS):
            skips.append(vid)
    placed = {vid for p in places for vid in p["videos"]}
    existing = {vid: slug for vid, slug in EXISTING.items() if vid in pending}
    skips = [s for s in skips if s not in placed and s not in existing]

    out = {"places": places, "skip": skips, "existing": existing}
    (ROOT / "data" / "suggestions.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    left = len(pending) - len(placed) - len(skips) - len(existing)
    print("\nPlaces suggested: %d | videos placed by suggestion: %d | suggested skips: %d | left for you: %d" % (
        len(places), len(placed), len(skips), left))
    print("Pins found: %d of %d" % (sum(1 for p in places if p["found"]), len(places)))


if __name__ == "__main__":
    main()
