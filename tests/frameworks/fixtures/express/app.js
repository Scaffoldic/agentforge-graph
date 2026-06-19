const express = require('express');

const app = express();
const router = express.Router();

function getUsers(req, res) {
  res.json([]);
}

app.get('/users', getUsers); // named handler -> HANDLED_BY
app.post('/items', (req, res) => { res.json({}); }); // anonymous handler -> Route only
router.get('/health', getUsers);

app.use('/api', router); // mount, not a route method
app.get(buildPath(), getUsers); // dynamic path -> unresolved
app.listen(3000); // not a route

module.exports = app;
